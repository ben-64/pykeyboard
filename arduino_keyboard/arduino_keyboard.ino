#include <WiFi.h>
#include <WiFiUdp.h>
#include "Adafruit_NeoTrellis.h"
#include "config.h"

#ifdef KEYBOARD_DEBUG
#define printf(args...) Serial.printf(args)
#else
#define printf(args...)
#endif

#define START_EVENT   255
#define RESTORE_EVENT 254

#define UDP_BUFFER 8192
typedef struct buf_t {
  char buf[UDP_BUFFER];
  uint32_t len;
} buf_t;
buf_t buffer;

typedef struct __attribute__((packed)) button_info_t {
  uint8_t  button;
  uint32_t color;
  uint8_t  delay;
} button_info_t;

boolean connected = false;
WiFiUDP udp;

void start_wifi() {
  printf("Connecting to WiFi network: %s\n",String(SSID));

  // delete old config
  WiFi.disconnect(true);
  //register event handler
  WiFi.onEvent(WiFiEvent);
  
  //Initiate connection
  WiFi.begin(SSID, PSK);

  printf("Waiting for WIFI connection...\n");
  while(!connected) delay(1000);
}

//wifi event handler
void WiFiEvent(WiFiEvent_t event){
    switch(event) {
      case SYSTEM_EVENT_STA_GOT_IP:
          //When connected set 
          printf("WiFi connected! IP address: %s\n",WiFi.localIP().toString());
          //initializes the UDP state
          //This initializes the transfer buffer
          udp.begin(WiFi.localIP(),UDP_PORT);
          connected = true;
          break;
      case SYSTEM_EVENT_STA_DISCONNECTED:
          printf("WiFi lost connection\n");
          connected = false;
          break;
      default: break;
    }
}

#define Y_DIM 8 //number of rows of key
#define X_DIM 8 //number of columns of keys

Adafruit_NeoTrellis t_array[Y_DIM/4][X_DIM/4] = {
    { Adafruit_NeoTrellis(0x2F), Adafruit_NeoTrellis(0x2E) },
    {Adafruit_NeoTrellis(0x30), Adafruit_NeoTrellis(0x31)}
};

//pass this matrix to the multitrellis object
Adafruit_MultiTrellis trellis((Adafruit_NeoTrellis *)t_array, Y_DIM/4, X_DIM/4);

// Input a value 0 to 255 to get a color value.
// The colors are a transition r - g - b - back to r.
uint32_t Wheel(byte WheelPos) {
  if(WheelPos < 85) {
   return seesaw_NeoPixel::Color(WheelPos * 3, 255 - WheelPos * 3, 0);
  } else if(WheelPos < 170) {
   WheelPos -= 85;
   return seesaw_NeoPixel::Color(255 - WheelPos * 3, 0, WheelPos * 3);
  } else {
   WheelPos -= 170;
   return seesaw_NeoPixel::Color(0, WheelPos * 3, 255 - WheelPos * 3);
  }
  return 0;
}

TrellisCallback pushed(keyEvent evt) {
  if(evt.bit.EDGE == SEESAW_KEYPAD_EDGE_FALLING) {
    send_event_button(evt.bit.NUM,0);
  } else if (evt.bit.EDGE == SEESAW_KEYPAD_EDGE_RISING) {
    printf("Push button %u\n",evt.bit.NUM);
    send_event_button(evt.bit.NUM,1);
  }
}

void send_event_button(uint8_t button,uint8_t pushed) {
  udp.beginPacket(UDP_SERVER,UDP_PORT);
  udp.write(button);
  udp.write(pushed);
  udp.endPacket();
}

// Sometimes, we can by desynchronised, we just send information to the server
// And reset the UDP connection
void handle_reception_problem() {
  send_event_button(RESTORE_EVENT,1);
  udp.stop();
  udp.begin(WiFi.localIP(),UDP_PORT);
  printf("Problem during reception\n");
}

// Basic receive data : parsePacket must have been called before
uint32_t raw_receive_pkt(char *data, uint32_t len) {
  return udp.read(data,len);
}

// Read at least len bytes of data when available
uint32_t receive_pkt(char *data, uint32_t len) {
#define MAX_FAIL 5
  uint32_t pkt_size = 0;
  uint8_t count = 0;

  while(pkt_size == 0 && count < MAX_FAIL) {
    printf("Waiting for data\n");
    pkt_size = udp.parsePacket();
    count += 1;
  }

  if(count == MAX_FAIL) {
    handle_reception_problem();
    return 0;
  }

  raw_receive_pkt(data,len);

  return pkt_size; 
}

// Receive UDP data. The first four bytes is the size of data that have been sent
// parsePacket must have been called before
bool receive_udp() {
  uint32_t len_packet;

  buffer.len = 0;

  raw_receive_pkt((char *)&len_packet, 4);
  printf("Size packet : %u\n",len_packet);

  while(buffer.len < len_packet) {
    uint32_t current_len;
    current_len = receive_pkt(buffer.buf+buffer.len, 1492);
    if(current_len == 0) return false;
    buffer.len += current_len;
  }

  printf("Ok data: sz %u\n",buffer.len);

  return true;
}


bool parse_binary_server_response() {
  button_info_t *info;

  if(receive_udp()) {
    printf("Start: 0x%02x End: 0x%02x  Len:%u\n",buffer.buf,(char*)(buffer.buf+buffer.len),buffer.len);
    for(info = (button_info_t *)buffer.buf; info < (button_info_t*)(buffer.buf+buffer.len); info++) {
      printf("button:[%u,%u,%u]\n",info->button,info->color,info->delay);
      action(info->button,info->color);
      if(info->delay != 0) {
        delay(info->delay);
      }
    }
    return true;
  }
  return false;
}


bool parse_server_response() {
  return parse_binary_server_response();
}


void action(const uint8_t button,const uint32_t color) {
  trellis.setPixelColor(button,color);
  trellis.show();
}


void start_animation() {
  if(!trellis.begin()){
    printf("failed to begin trellis\n");
    while(1);
  }

  /* the array can be addressed as x,y or with the key number */
  for(int i=0; i<Y_DIM*X_DIM; i++){
      trellis.setPixelColor(i, Wheel(map(i, 0, X_DIM*Y_DIM, 0, 255))); //addressed with keynum
      trellis.show();
      delay(10);
  }
  
  for(int y=0; y<Y_DIM; y++){
    for(int x=0; x<X_DIM; x++){
      //activate rising and falling edges on all keys
      trellis.activateKey(x, y, SEESAW_KEYPAD_EDGE_RISING, true);
      trellis.activateKey(x, y, SEESAW_KEYPAD_EDGE_FALLING, true);
      trellis.registerCallback(x, y, pushed);
      trellis.setPixelColor(x, y, 0x000000); //addressed with x,y
      trellis.show(); //show all LEDs
      delay(10);
    }
  }  
}


void setup() {
  Serial.begin(9600);

  start_wifi();
  // Useless animation for starting, but it's fun :p
  start_animation();
  send_event_button(START_EVENT,1);
}


void loop() {
  trellis.read();
  if(udp.parsePacket() != 0) {
    parse_server_response();
  } else {
  }
  delay(10);
}
