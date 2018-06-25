'''
door phone system with raspberry pi
using telegram as client control
gpio usage :
gpio    function
12      relay bell
16      relay selenoid
20      sw bell
21      sw open selenoid
'''

import sys
import time
import datetime
import logging
import requests
import threading
import subprocess
import os

from telethon import TelegramClient, events

#gpio
import RPi.GPIO as GPIO

CMD_PHOTO_FILENAME = "/tmp/cam.jpg"
CMD_CAPTURE_PHOTO = "fswebcam -q -d /dev/video0 -S3 -r 320x240 " + CMD_PHOTO_FILENAME
CMD_VIDEO_FILENAME = "/tmp/cam.mpg"
CMD_CAPTURE_VIDEO = "ffmpeg -v 0 -y -f v4l2 -s 320x480 -i /dev/video0 -t 10 -preset ultrafast -crf 25 " + CMD_VIDEO_FILENAME
CMD_PLAY_SND = "aplay -D sysdefault:CARD=AUDIO %s"

SOUND_LIST = {
    "TUNGGU" : "snd_tunggu.wav",
    "BUKA" : "snd_buka.wav",
    "BUKA2" : "snd_buka2.wav",
    "TOLAK" : "snd_tolak.wav",
    "TOLAK2": "snd_tolak2.wav"
}

TELEGRAM_CLIENT_SETTING = {
    "ID" : xxx,
    "HASH" : 'xxx',
    "SESSION" : 'rpi_telegram_cli',
    "USER_ID_MASTER" : '@xxx'
    #"USER_ID_MASTER" : '@Azmyasya'
}

'''
https://stackoverflow.com/questions/7621897/python-logging-module-globally
'''
def setup_custom_logger(name):
    formatter = logging.Formatter(fmt='%(asctime)s - %(levelname)s - %(module)s - %(message)s')

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    return logger
    
'''
main logger object
'''    
logger = setup_custom_logger('root')
logger.debug('Door phone started')

'''
utility class
'''
class Utility(object):

    @staticmethod
    # get error
    def get_error_msg():
        try:
            return sys.exc_info()[1]
        except:
            pass
            return            
    
    '''
    start a process to be threading in daemonize mode
    ref:
    - https://stackoverflow.com/questions/30913201/pass-keyword-arguments-to-target-function-in-python-threading-thread
    - https://gist.github.com/sunng87/5152427
    '''
    @staticmethod
    def start_daemon(f=None, args=None):
        if not f is None:
            if not args is None:
                t = threading.Thread(target=f, kwargs=args)
            else:
                t = threading.Thread(target=f)
            t.setDaemon(True)
            t.start()
            
'''
gpio main class
'''
class GPIOObject(object):
    '''
    gpio usage :
    gpio    function
    12      relay bell
    16      relay selenoid
    20      sw bell
    21      sw open selenoid
    '''
    
    gpio_list = {
    'rly_bell': (12, GPIO.OUT, GPIO.LOW), 
    'rly_door': (16, GPIO.OUT, GPIO.LOW),  
    'sw_bell': (20, GPIO.IN, GPIO.PUD_UP),  
    'sw_door': (21, GPIO.IN, GPIO.PUD_UP)
    }
    
    def __init__(self, on_door_change=None, on_bell_pressed=None):
        self.on_door_change = on_door_change
        self.on_bell_pressed = on_bell_pressed
        self.gpio_setup()
        
    # setup the gpio
    def gpio_setup(self):
        try:
            self.bell_active = False
            self.door_opened = False
    
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            
            for pin_io in self.gpio_list:
                #logger.debug(pin_io)
                if self.gpio_list[pin_io][1] is GPIO.OUT:
                    GPIO.setup(self.gpio_list[pin_io][0],
                    self.gpio_list[pin_io][1],
                    initial=self.gpio_list[pin_io][2])
                else:
                    GPIO.setup(self.gpio_list[pin_io][0],
                    self.gpio_list[pin_io][1],
                    pull_up_down=self.gpio_list[pin_io][2])
                                
            GPIO.add_event_detect(self.gpio_list['sw_door'][0], GPIO.FALLING, callback=self.sw_door_callback, bouncetime=1000) 
            GPIO.add_event_detect(self.gpio_list['sw_bell'][0], GPIO.FALLING, callback=self.sw_bell_callback, bouncetime=1000)
            
            self.time_last_door_opened = self.time_last_sw_bell_pressed = time.time()
            
            Utility.start_daemon(self.door_bell_timeout_checker)
            
            self.is_initialize = True
                
            logger.debug("Init gpio ok")
            
            return (0,'')
        except:
            pass
            logger.error("Init gpio fail %s" % (Utility.get_error_msg(),))
            self.is_initialize = False
            return (1,Utility.get_error_msg())
            
    # cleanup gpio
    def gpio_cleanup(self):
        try:
            GPIO.cleanup()
        except:
            pass

    def door_open(self, isopened=True):
        GPIO.output(self.gpio_list['rly_door'][0], isopened )
        msg = "Door is %s" % (GPIO.input(self.gpio_list['rly_door'][0]) and "OPENED" or "CLOSED")
        
        if GPIO.input(self.gpio_list['rly_door'][0]):
            self.time_last_door_opened = time.time()
            self.door_opened = True
        else:
            self.door_opened = False
            
        logger.debug(msg)        
            
    def sw_door_callback(self, channel):
        try:
            logger.debug("Door switch pressed")
            self.door_open(not GPIO.input(self.gpio_list['rly_door'][0]))
            
            msg = "Door is %s" % (GPIO.input(self.gpio_list['rly_door'][0]) and "OPENED" or "CLOSED")
            #telegram_client.send_message(TELEGRAM_CLIENT_SETTING['USER_ID_MASTER'], msg)
            #print(self.on_door_change)
            if self.on_door_change is not None:
                self.on_door_change()
        except:
            pass
            
    def sw_bell_callback(self, channel):
        try:
            logger.debug("Bell switch pressed")
            GPIO.output(self.gpio_list['rly_bell'][0], GPIO.HIGH )
            time.sleep(1)
            GPIO.output(self.gpio_list['rly_bell'][0], GPIO.LOW )
            self.bell_active = True
            self.time_last_sw_bell_pressed = time.time()
            
            #telegram_client.send_message(TELEGRAM_CLIENT_SETTING['USER_ID_MASTER'], "Somebody knocking your door")
            if self.on_bell_pressed is not None:
                self.on_bell_pressed()
        except:
            pass
            
    def door_bell_timeout_checker(self):
        while True:
            #logger.debug("Checking door and bell failsafe time")
            
            tnow = time.time()
            if (tnow-self.time_last_door_opened)>=15:
                self.time_last_door_opened = tnow
                self.door_open(False)
                logger.debug("Door closed")
                
            if (tnow-self.time_last_sw_bell_pressed)>=10:
                self.time_last_sw_bell_pressed = tnow
                if self.bell_active:
                    self.bell_active = False
                    logger.debug("Reset bell status")
                
            time.sleep(1)

'''
telegram client object
'''
class TelegramClientObj(object):

    def __init__(self, telegram_setting = None, message_handler_callback = None):
        try:
            self.message_handler_callback = message_handler_callback
            self.user_master_id = telegram_setting['USER_ID_MASTER']
            self.telegram_cli = TelegramClient(
                telegram_setting['SESSION'], 
                telegram_setting['ID'], 
                telegram_setting['HASH'], 
                update_workers=1, 
                spawn_read_thread=False)
            self.telegram_cli.add_event_handler(self.new_message_handler, events.NewMessage)
            self.telegram_cli.start()
            self.initialize = True
            logger.debug("TelegramClient initialize")
        except Exception as err:
            pass
            self.initialize = False
            self.telegram_cli = None
            logger.error("TelegramClient fail %s" % (Utility.get_error_msg(),))
            
    def new_message_handler(self, event):
        try:
            logger.debug(event)
            if self.message_handler_callback is not None:
                self.message_handler_callback(self, event)
        except Exception as err:
            pass
            logger.error(Utility.get_error_msg())
            
    def reply_message(self, to=None, msg=None):
        try:
            self.telegram_cli.send_message("me", msg)
            # self.telegram_cli.send_message(self.user_master_id, msg)
            if to is not None:
                self.telegram_cli.send_message(to, msg)
        except Exception as err:
            pass
            logger.error(Utility.get_error_msg())
            
    def reply_file(self, to=None, filex=None):
        try:
            self.telegram_cli.send_file("me", filex)
            # self.telegram_cli.send_file(self.user_master_id, filex)
            if to is not None:
                self.telegram_cli.send_file(to, filex)
        except Exception as err:
            pass
            logger.error(Utility.get_error_msg())
            
    def start_loop(self):
        try:
            self.telegram_cli.idle()
        except Exception as err:
            pass
            logger.error(Utility.get_error_msg())
            
def runcommand (cmd):
    proc = subprocess.Popen(cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            shell=True,
                            universal_newlines=True)
    std_out, std_err = proc.communicate()
    return proc.returncode, std_out, std_err            
            
def telegram_cmd_handler(clix, eventx):
    try:
        logger.debug("Get message : %s" % (eventx.raw_text,))
        #logger.debug(eventx.sender)
        if eventx.sender.is_self:
            userx = None
        else:
            userx = '@' + eventx.sender.username
        cmdx = eventx.raw_text.strip().lower()
        
        if cmdx == 'foto':
            logger.debug("Ambil gambar...")
            try:
                if os.path.exists(CMD_PHOTO_FILENAME):
                    os.remove(CMD_PHOTO_FILENAME)
            except Exception as err:
                pass
                
            clix.reply_message(userx, "Mulai mengambil foto. Mohon tunggu!!!")
            logger.debug("Mengambil gambar mulai...")
            status = runcommand(CMD_CAPTURE_PHOTO)
            logger.debug(status)
            if status[1] == '' and status[2] == '':
                logger.debug("Mengirim gambar...")
                clix.reply_file(userx, CMD_PHOTO_FILENAME)
            else:
                clix.reply_message(userx, "Gagal mengambil gambar!!!")
                
        elif cmdx == 'video':
            logger.debug("Ambil video...")
            try:
                if os.path.exists(CMD_VIDEO_FILENAME):
                    os.remove(CMD_VIDEO_FILENAME)
            except Exception as err:
                pass
                
            clix.reply_message(userx, "Mulai mengambil video. Mohon tunggu!!!")
            logger.debug("Mengambil video mulai...")
            status = runcommand(CMD_CAPTURE_VIDEO)
            logger.debug(status)
            if status[1] == '':
                logger.debug("Mengirim video...")
                clix.reply_file(userx, CMD_VIDEO_FILENAME)
            else:
                clix.reply_message(userx, "Gagal mengambil video!!!")
        
        elif cmdx == 'tolak':
            door_gpio.door_open(False)
            logger.debug("Menolak...")
            status = runcommand(CMD_PLAY_SND % (SOUND_LIST['TOLAK'],))
            logger.debug(status)
            if status[1] == '':
                clix.reply_message(userx, "Tamu telah diberitahu lewat pengeras suara dengan sukses")
            else:
                clix.reply_message(userx, "Gagal memberitahu Tamu lewat pengeras suara!!!")
            
        elif cmdx == 'tolak 2':
            door_gpio.door_open(False)
            logger.debug("Suruh balik...")
            status = runcommand(CMD_PLAY_SND % (SOUND_LIST['TOLAK2'],))
            logger.debug(status)
            if status[1] == '':
                clix.reply_message(userx, "Tamu telah diberitahu lewat pengeras suara dengan sukses")
            else:
                clix.reply_message(userx, "Gagal memberitahu Tamu lewat pengeras suara!!!")
            
        elif cmdx == 'tunggu':
            logger.debug("Menunggu...")
            status = runcommand(CMD_PLAY_SND % (SOUND_LIST['TUNGGU'],))
            logger.debug(status)
            if status[1] == '':
                clix.reply_message(userx, "Tamu telah diberitahu lewat pengeras suara dengan sukses")
            else:
                clix.reply_message(userx, "Gagal memberitahu Tamu lewat pengeras suara!!!")
            
        elif cmdx == 'buka':
            door_gpio.door_open()
            logger.debug("Membuka pintu...")
            status = runcommand(CMD_PLAY_SND % (SOUND_LIST['BUKA'],))
            logger.debug(status)
            if status[1] == '':
                clix.reply_message(userx, "Tamu telah diberitahu lewat pengeras suara dengan sukses")
            else:
                clix.reply_message(userx, "Gagal memberitahu Tamu lewat pengeras suara!!!")
            
        elif cmdx == 'buka 2':
            door_gpio.door_open()
            logger.debug("Membuka pintu dan tamu duduk...")
            status = runcommand(CMD_PLAY_SND % (SOUND_LIST['BUKA2'],))
            logger.debug(status)
            if status[1] == '':
                clix.reply_message(userx, "Tamu telah diberitahu lewat pengeras suara dengan sukses")
            else:
                clix.reply_message(userx, "Gagal memberitahu Tamu lewat pengeras suara!!!")
            
        else:
            clix.reply_message(userx, "Perintah tidak dikenal!!!")
            
    except Exception as err:
        pass
        logger.error(Utility.get_error_msg())
    
'''
main program start here
'''            
door_gpio = None
tele_cli = None

if __name__ == "__main__":
    try:
        '''
        #print(datetime.datetime.now())
        iotx = IoT_Server()
        
        while True:
            iotx.send_status()
            time.sleep(10)
        '''            
        
        tele_cli = TelegramClientObj(TELEGRAM_CLIENT_SETTING, message_handler_callback=telegram_cmd_handler)
                
        def send_bell_status():
            tele_cli.reply_message(msg="Someone is knocking your door!")
            
        def send_door_status():
            tele_cli.reply_message(msg="Door is %s" % (door_gpio.door_opened and "OPENED" or "CLOSED"))
        
        #global door_gpio
        door_gpio = GPIOObject(on_bell_pressed = send_bell_status, on_door_change = send_door_status)
        
        if tele_cli.initialize:
            logger.debug("TelegramClient idling...")        
            tele_cli.start_loop()
        else:
            logger.error("Cannot start TelegramClient. Will exit....")
        
        '''
        while True:
            time.sleep(1)
        '''
    except Exception as errx:
        pass
        logger.error("Error = %s" % errx)
        
    try:
        logger.debug("Cleaning up")
        door_gpio.gpio_cleanup();
    except:
        pass
        
    logger.debug("Exit")            