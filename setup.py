from setuptools import setup

with open("README.md", 'r') as f:
    long_description = f.read()

setup(
    name='pykeyoard',
    version='0.64',
    description='Toolz to manage Adafruit keyboard',
    long_description=long_description,
    author='ben64',
    author_email='ben64@time0ut.org',
    scripts=["pykeyboard.py"]
)
