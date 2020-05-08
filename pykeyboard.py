#!/usr/bin/env python3

import sys
import socket
import struct
import json
import random
import subprocess
import time


class Protocol(object):
    def __init__(self):
        self.buffer = []

    def add(self,button,color,delay=0):
        self.buffer.append((button,color,delay))

    def commit(self):
        res = self.generate()
        self.buffer = []
        return res


class JsonProtocol(Protocol):
    def generate(self):
        res = []
        for button,color,delay in self.buffer:
            if delay != 0:
                res.append({"button":button,"color":color,"delay":delay})
            else:
                res.append({"button":button,"color":color})
        if len(res) > 0:
            return json.dumps(res).encode("ascii")
        return None


class BinaryProtocol(Protocol):
    def generate(self):
        res = b""
        for button,color,delay in self.buffer:
            res += struct.pack("<BIB",button,color,delay)
        return res


class Keyboard(object):
    def __init__(self,protocol=BinaryProtocol):
        self.protocol = protocol()
        self.reset()
        self.brightness = 0.1

    def set_application(self,app):
        self.application = app
        self.application.init()

    def apply_brightness(self,color):
        r,g,b = color>>16,((color>>8)&0xFF),(color&0xFF)
        color = int(r*self.brightness)<<16 | int(g*self.brightness)<<8 | int(self.brightness*b)
        return color

    @classmethod
    def to_coord(cls,i):
        return (int(i/8),i%8)

    @classmethod
    def from_coord(cls,x,y):
        return x*8+y

    def __getitem__(self,p):
        button = Keyboard.from_coord(p[0],p[1])
        return self.buffer[button]

    def __setitem__(self,p,v):
        button = Keyboard.from_coord(p[0],p[1])
        self.buffer[button] = v
 
    def set_color(self,x,y,color,delay=0):
        self.protocol.add(Keyboard.from_coord(x,y),self.apply_brightness(color),delay)
        self[x,y] = color

    def on(self,x,y,color,delay=0):
        self.set_color(x,y,color,delay)

    def off(self,x,y,delay=0):
        self.set_color(x,y,0,delay)

    def is_on(self,x,y):
        return self[x,y] != 0

    def is_off(self,x,y):
        return not self.is_on(x,y)

    def increase_brightness(self,inc=0.1):
        self.set_brightness(self.brightness+inc)

    def decrease_brightness(self,dec=0.1):
        self.set_brightness(self.brightness-dec)

    def set_brightness(self,bright):
        self.brightness = max(0.0,min(1.0,bright))
        for i in range(8):
            for j in range(8):
                self.set_color(i,j,self[i,j])

    def reset(self):
        self.buffer = [0]*64

    def restore(self):
        for i in range(8):
            for j in range(8):
                self.on(i,j,self[i,j])

    def commit(self):
        data = self.protocol.commit()
        if data:
            self.send(data)

    def clear(self,everything=False):
        for i in range(8):
            for j in range(8):
                if not self.is_off(i,j) or everything: self.off(i,j)

    def run(self):
        self.init()
        while True:
            button_id,pushed = self.recv()
            res = self.handle_event(button_id,pushed)
            self.commit()

    def handle_event(self,event,pushed):
        if event == 255:
            self.application.init()
        elif event == 254:
            self.application.restore()
        elif event <= 63:
            self.handle_button(event,pushed)

    def handle_button(self,button,pushed):
        self.application.event_button(button,pushed)


class Application(object):
    def __init__(self,keyboard):
        self.keyboard = keyboard
        self.terminated = False

    def __getitem__(self,p):
        button = self.keyboard.from_coord(p[0],p[1])
        return self.buffer[button]

    def __setitem__(self,p,v):
        button = self.keyboard.from_coord(p[0],p[1])
        self.buffer[button] = v

    def __getattr__(self,x):
        return getattr(self.keyboard,x)

    def event_button(self,button,pushed):
        x,y = self.keyboard.to_coord(button)
        self.event_button_xy(x,y,pushed)

    def event_button_xy(self,x,y,pushed):
        if pushed:
            self.event_push_xy(x,y)
        else:
            self.event_pull_xy(x,y)

    def event_pull_xy(self,x,y):
        pass

    def event_push_xy(self,x,y):
        pass

    def init(self):
        # Clear must be called before reset
        self.keyboard.clear()
        self.keyboard.reset()
        self.terminated = False
        #print("Application %r started" % (self,))

    def terminate(self):
        self.terminated = True
        self.commit()
        #print("Application %r terminated" % (self,))

    def is_terminated(self):
        return self.terminated


class MainApplication(Application):
    """ Main application, launch new applications """
    def __init__(self,keyboard,conf):
        super().__init__(keyboard)
        self.current_app = None
        self.conf = self.load_configuration(conf)

    def init(self):
        super().init()
        self.current_app = None

    def load_configuration(self,path):
        with open(path,"rb") as f:
            return json.load(f)

    def launch_appli(self,cmd):
        parenthesis = cmd.find('(')
        if parenthesis == -1:
            return None
        cmd = cmd[:parenthesis+1] + "self.keyboard," + cmd[parenthesis+1:]
        return eval(cmd)

    def event_button(self,button,pushed):
        # Proxy mode
        if self.current_app:
            self.current_app.event_button(button,pushed)
            if self.current_app.is_terminated():
                self.current_app = None
                self.init()
        else:
            button = str(button)
            if pushed and button == "63":
                self.clear(everything=True)
            elif not pushed and button in self.conf:
                self.current_app = self.launch_appli(self.conf[button])
                if self.current_app:
                    self.current_app.init()


class CmdApplication(Application):
    """ Application excuting command on push button """
    def __init__(self,keyboard,conf):
        super().__init__(keyboard)
        self.conf = self.load_configuration(conf)

    def load_configuration(self,path):
        with open(path,"rb") as f:
            return json.load(f)

    def init(self):
        super().init()
        for button,conf in self.conf.items():
            if "color" in conf:
                x,y = self.keyboard.to_coord(int(button))
                self.on(x,y,conf["color"])

    def event_push_xy(self,x,y):
        button = str(self.keyboard.from_coord(x,y))
        if button in self.conf and "cmd" in self.conf[button]:
            subprocess.check_output(self.conf[button]["cmd"],stderr=subprocess.STDOUT,shell=True)
        elif (x,y) == (7,7):
            self.terminate()


class Basic(Application):
    def event_push_xy(self,x,y):
        change_colors = {0:0xFF,0xFF:0xFF00,0xFF00:0xFFFF,0xFFFF:0xFF0000,0xFF0000:0xFF00FF,0xFF00FF:0xFFFF00,0xFFFF00:0xFFFFFF,0xFFFFFF:0}
        if (x,y) == (7,7):
            self.terminate()
        else:
            self.on(x,y,change_colors[self[x,y]])


class Test(Application):
    def init(self):
        t = [0xFF,0xFF00,0xFFFF,0xFF0000,0xbd4200,0xFFFF00,0xb1004e,0x5100ae]
        for i in range(len(t)):
            x,y = self.keyboard.to_coord(i)
            self.on(x,y,t[i])

        self.commit()


class BrightnessApplication(Application):
    """ Allow to change Brightness of the keyboard """
    def init(self):
        super().init()
        colors = [0xFF,0xFF00,0xFFFF,0xFF0000,0xbd4200,0xFFFF00,0xb1004e,0x5100ae]
        for i in range(8):
            self.on(7,i,colors[i])
        self.on(0,0,0xFF00)
        self.on(0,7,0xFF00000)

    def event_pull_xy(self,x,y):
        if (x,y) == (0,0):
            self.decrease_brightness()
        elif (x,y) == (0,7):
            self.increase_brightness()
        elif (x,y) == (7,7):
            self.terminate()


class Sudoku(Application):
    COLORS = [0xFF,0xFF00,0xFFFF,0xFF0000,0xbd4200,0xFFFF00,0xb1004e,0x5100ae]

    def init(self):
        super().init()
        self.generate_game()

    def generate_game(self):
        self.fixed_buttons = []
        self.add_fixed_button(0,0,4)
        self.add_fixed_button(0,3,2)
        self.add_fixed_button(0,4,1)
        self.add_fixed_button(0,6,3)
        self.add_fixed_button(1,1,7)
        self.add_fixed_button(1,5,2)
        self.add_fixed_button(2,2,2)
        self.add_fixed_button(2,4,5)
        self.add_fixed_button(2,6,7)
        self.add_fixed_button(3,0,7)
        self.add_fixed_button(3,3,5)
        self.add_fixed_button(3,7,3)
        self.add_fixed_button(4,0,6)
        self.add_fixed_button(4,4,3)
        self.add_fixed_button(4,7,1)
        self.add_fixed_button(5,1,1)
        self.add_fixed_button(5,3,3)
        self.add_fixed_button(5,5,8)
        self.add_fixed_button(6,2,7)
        self.add_fixed_button(6,6,8)
        self.add_fixed_button(7,1,6)
        self.add_fixed_button(7,3,8)
        self.add_fixed_button(7,4,4)
        self.add_fixed_button(7,7,5)

    def add_fixed_button(self,x,y,number):
        self.fixed_buttons.append((x,y))
        self.on(x,y,self.COLORS[number-1])

    def is_fixed_button(self,x,y):
        """ Is x,y fixed button """
        return (x,y) in self.fixed_buttons

    def available_colors(self,x,y):
        """ Return a list of available colors for this position """
        available_colors = set(self.COLORS[:])
        line_colors = set([])
        column_colors = set([])
        rectangle_colors = set([])

        starty = 0 if y<4 else 4
        startx = x-1 if x%2 == 1 else x

        for i in range(8):
            if not self.is_off(x,i):
                column_colors.add(self[x,i])
            if not self.is_off(i,y):
                line_colors.add(self[i,y])
            rx = int(i/4)+startx
            ry = starty+(i%4)
            if not self.is_off(rx,ry):
                rectangle_colors.add(self[rx,ry])

        available_colors = available_colors - column_colors
        available_colors = available_colors - line_colors
        available_colors = available_colors - rectangle_colors

        if self.is_on(x,y):
            available_colors.add(self[x,y])
        return list(available_colors)

    def next_color(self,x,y):
        """ Return the next color available if this button is pushed """
        available_colors = self.available_colors(x,y)
        current_color = self[x,y]

        try:
            indice_color = self.COLORS.index(current_color)
        except ValueError:
            indice_color = -1

        for i in range(indice_color+1,len(self.COLORS)):
            if self.COLORS[i] in available_colors:
                return self.COLORS[i]

        return 0

    def is_victory(self):
        for i in range(8):
            line = self.buffer[i*8:(i*8)+8]
            if len(set(self.COLORS) - set(line)) != 0: return False

            column = [self.buffer[j] for j in range(i,64+i,8)]
            if len(set(self.COLORS) - set(column)) != 0: return False

            offset = 0 if i%2 == 0 else -4
            rectangle = [self.buffer[j] for j in list(range(i*8+offset,i*8+4+offset))+list(range((i+1)*8+offset,(i+1)*8+4+offset))]
            if len(set(self.COLORS) - set(rectangle)) != 0: return False

        return True

    def event_pull_xy(self,x,y):
        if self.is_fixed_button(x,y):
            return

        color = self.next_color(x,y)
        self.on(x,y,color)
        if self.is_victory():
            for i in range(8):
                for j in range(8):
                    self.on(i,j,color)
            time.sleep(2)
            self.terminate()
 

class PhiloGame(Application):
    """ Useless game, does not really work """
    def event_pull_xy(self,x,y):
        if self.is_on(x,y):
            return 
        else:
            self.on(x,y,color)
               
        dec = ((-1,0),(0,-1),(0,1),(1,0))
        for xdir,ydir in dec:
            if x+xdir < 0 or x+xdir > 7 or y+ydir < 0 or y+ydir > 7: continue
            side_button = Keyboard.from_coord(x+xdir,y+ydir)
            if self.is_on(x+xdir,y+ydir):
                self.off(x+xdir,y+ydir)
            else:
                if x+2*xdir < 0 or x+2*xdir > 7 or y+2*ydir < 0 or y+2*ydir > 7: continue
                if self.is_on(x+2*xdir,y+2*ydir):
                    self.on(x+xdir,y+ydir,color)
        return


class Power4(Application):
    def __init__(self,keyboard):
        super().__init__(keyboard)
        self.user1 = True
 
    def is_aligned(self,x,y,need=4):
        color = self[x,y]

        directions = ( (1,0) , (0,1) , (1,1) , (1,-1) )
        for xdir,ydir in directions:
            align = 1
            
            for inc in range(-1,-need,-1):
                i = x+xdir*inc
                j = y+ydir*inc
                if i<0 or i>7 or j<0 or j>7: break
                if self[i,j] == color:
                    #print("[%u,%u] => on [align=%u]" % (i,j,align))
                    align += 1
                    if align == 4: return True
                else:
                    #print("[%u,%u] => off [align=%u]" % (i,j,align))
                    break
            for inc in range(1,need):
                i = x+xdir*inc
                j = y+ydir*inc
                if i<0 or i>7 or j<0 or j>7: break
                if self[i,j] == color:
                    #print("[%u,%u] => on [align=%u]" % (i,j,align))
                    align += 1
                    if align == 4: return True
                else:
                    #print("[%u,%u] => off [align=%u]" % (i,j,align))
                    break
        return False

    def event_pull_xy(self,x,y):
        color = 0xFF if self.user1 else 0xFF0000

        for j in range(7,-1,-1):
            if self.is_off(x,j):
                self.on(x,j,color)

                ## Check end game
                if self.is_aligned(x,j):
                    for i in range(8):
                        for j in range(8):
                            self.on(i,j,color)
                    self.terminate()
                    time.sleep(2)
                break
        else:
            return
        self.user1 = not self.user1


class Quizz(Application):
    def __init__(self,keyboard,ip="127.0.0.1",port=64243):
        super().__init__(keyboard)
        self.dst = (ip,port)
        self.sock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        base = 4
        self.keys = {(base+0,0):b"1",(base+0,1):b"2",(base+0,2):b"3",(base+1,0):b"4",(base+1,1):b"5",(base+1,2):b"6",(base+2,0):b"7",(base+2,1):b"8",(base+2,2):b"9",(base+3,0):b"0"}

    def init(self):
        super().init()
        for k,v in self.keys.items():
            self.on(k[0],k[1],0x444444)

    def event_push_xy(self,x,y):
        if (x,y) == (7,7):
            self.terminate()
        elif (x,y) in self.keys:
            self.sock.sendto(self.keys[(x,y)],self.dst)


class SecretKey(Application):
    def __init__(self,keyboard,level=1):
        super().__init__(keyboard)
        self.level = level
        
    def init(self):
        super().init()
        self.randomx = random.randint(0,7)
        self.randomy = random.randint(0,7)

    def event_pull_xy(self,x,y):
        for i,j in ((0,0),(0,7),(0,3),(3,0),(3,7),(7,0),(7,3),(7,7)):
            self.off(i,j)
        self.commit()

        if self.level < 2:
            self.on(x,y,0xFFFFFF)

        if x == self.randomx and y == self.randomy:
            for i in range(8):
                for j in range(8):
                    self.on(i,j,0xFFFF00)
            self.terminate()
            time.sleep(2)
            return
        
        if self.randomx > x:
            displayx = 7
        elif self.randomx < x:
            displayx = 0
        else:
            displayx = 3

        if self.randomy > y:
            displayy = 7
        elif self.randomy < y:
            displayy = 0
        else:
            displayy = 3

        self.on(displayx,displayy,0xFF)


class UDPKeyboard(Keyboard):
    def __init__(self,port=64241,*args,**kargs):
        super().__init__(*args,**kargs)
        self.port = port
        self.sock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)

    def init(self):
        self.sock.bind(("0.0.0.0",self.port))

    def recv(self):
        data,self.addr_keyboard = self.sock.recvfrom(4096)
        return struct.unpack("BB",data)

    def send(self,data):
        self.sock.sendto(struct.pack("<I",len(data)),self.addr_keyboard)
        for i in range(0,len(data),1400):
            self.sock.sendto(data[i:i+1400],self.addr_keyboard)


if __name__ == "__main__":
    keyboard = UDPKeyboard()
    app = MainApplication(keyboard,conf=sys.argv[1])
    keyboard.set_application(app)
    keyboard.run()
