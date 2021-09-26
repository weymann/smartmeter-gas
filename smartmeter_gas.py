#!/usr/bin/python3

import py_qmc5883l
import paho.mqtt.client as mqtt
import paho.mqtt.publish as publish
import ssl
import time
import json
import asyncio
import background
import logging
import os
import sys
from datetime import datetime
from datetime import date
from systemd.journal import JournaldLogHandler

# Needed dependency:
# https://github.com/RigacciOrg/py-qmc5883l

host = ""
token = ''
normal = 0
hysteresis = 0
read_interval = 2
tick_idle_interval = 3
sensor_init = 0
openhab_access = 0
state = "init"
loop_counter = 1
loop_time = 60
gas_meter_total = 0
gas_meter_year = 0
gas_meter_month = 0
gas_meter_day = 0
gas_meter_minute = 0
read_success = 0
read_fail = 0
success_rate = 0.0
running = False
mqtt_connected = False
mqtt_client = mqtt.Client(client_id='', clean_session=True, userdata=None, protocol=mqtt.MQTTv311, transport="tcp")
mqtt_topic = ""
smartmeter_data = "{}"
kwh_calculation = False
kwh_factor = 0
price_calculation = False
price_factor = 0

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))# get an instance of the logger object this module will use

@background.task
def mqtt_loop():
    while running:
        mqtt_client.loop()
        time.sleep(1)
        

@background.task
def mqtt_connect():
  log("MQTT Client connect")
  connectionResult = mqtt_client.connect(config_json["mqtt_server"],config_json["mqtt_port"])

@background.task
def publish():
    #global price_claculation
    global mqtt_connected
    global mqtt_topic
    log("Publish Connected? "+str(mqtt_connected))
    if not(mqtt_connected):
        mqtt_connect()
           	
    mqtt_client.publish(mqtt_topic+"/timestamp",datetime.now().strftime("%d/%m/%y %H:%M:%S"))
    mqtt_client.publish(mqtt_topic+"/total",gas_meter_total)
    data_json["total"] = gas_meter_total
    mqtt_client.publish(mqtt_topic+"/day",gas_meter_day)
    data_json["day"] = gas_meter_day
    mqtt_client.publish(mqtt_topic+"/month",gas_meter_month)
    data_json["month"] = gas_meter_month
    mqtt_client.publish(mqtt_topic+"/year",gas_meter_year)
    data_json["year"] = gas_meter_year
    mqtt_client.publish(mqtt_topic+"/minute",gas_meter_minute)
    mqtt_client.publish(mqtt_topic+"/success",success_rate)
    data_json["sucess_rate"] = success_rate
    if kwh_calculation :
        mqtt_client.publish(mqtt_topic+"/total-kwh",gas_meter_total * kwh_factor)
        mqtt_client.publish(mqtt_topic+"/day-kwh",gas_meter_day * kwh_factor)
        mqtt_client.publish(mqtt_topic+"/month-kwh",gas_meter_month * kwh_factor)
        mqtt_client.publish(mqtt_topic+"/year-kwh",gas_meter_year * kwh_factor)
    
    if price_calculation :
        mqtt_client.publish(mqtt_topic+"/total-price",gas_meter_total * price_factor)
        mqtt_client.publish(mqtt_topic+"/day-price",gas_meter_day * price_factor)
        if config_json["gas_fee_month"] :
            mqtt_client.publish(mqtt_topic+"/month-price",gas_meter_month * price_factor + config_json["gas_fee_month"])
            mqtt_client.publish(mqtt_topic+"/year-price",gas_meter_year * price_factor + config_json["gas_fee_month"] * last_sensor_date.month)
        else :
            mqtt_client.publish(mqtt_topic+"/month-price",gas_meter_month * price_factor)
            mqtt_client.publish(mqtt_topic+"/year-price",gas_meter_year * price_factor)

# log message towards systemd (started as service) plus command line (started manually)
def log(message):
	logging.info(message)
	#now = datetime.now()
	#current_time = now.strftime("%d/%m/%y %H:%M:%S")
	#print(current_time + " : " + message)

def on_connect(client, userdata, flags, rc):
	if rc == 0:
		global mqtt_connected
		mqtt_connected = True
		log("Connected to MQTT Broker! " + str(mqtt_connected))
	else:
		log("Failed to connect, return code %d\n", rc)

def on_disconnect(client, userdata, flags, rc):
		global mqtt_connected
		mqtt_connected = False

def on_log(client, userdata, level, buf):
    logging.info(buf)

#define callbacks
def on_message(client, userdata, message):
  print("received message =",str(message.payload.decode("utf-8")))

def on_publish(client,userdata,result):             #create function for callback
    log("data published "+str(result))
    pass


# program start
last_sensor_date = datetime.today().date()

# Read config file
execution_path = ""
file_path = __file__.split("/")
length = len(file_path)-1
for i in range(length):
    if i == 0:
        execution_path = execution_path + file_path[i]
    else:
        execution_path = execution_path + "/" + file_path[i]
log(execution_path)
config_file = open(execution_path+"/config.json", "r")
config_json = json.loads(config_file.read())
kwh_calculation = "heating_value" in config_json and "z_number" in config_json
if kwh_calculation :
    kwh_factor = config_json["heating_value"] * config_json["z_number"] / 1000.0
    log("Kwh Factor " + str(kwh_factor))
    price_calculation = "gas_price" in config_json
    if price_calculation :
        price_factor = kwh_factor * config_json["gas_price"]
        log("Price Factor " + str(price_factor))
    else :
        log("No price calculation")
else :
    log("No kwh calculation")
    
log(config_json)

# Read stored data file with last stored values
data_file = open(execution_path+"/data.json", "r")
data_json = json.loads(data_file.read())
gas_meter_total = data_json["total"]
gas_meter_month = data_json["month"]
gas_meter_year = data_json["year"]
gas_meter_day = data_json["day"]
log(data_json)

# set values for device driver
normal = config_json["device_value_idle"]
hysteresis = config_json["device_value_hysteresis"]


# MQTT Client setup
mqtt_topic = config_json["mqtt_topic"]
#mqtt_client.on_log = on_log
mqtt_client.on_publish = on_publish
mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect

if config_json["mqtt_user"] : 
    mqtt_client.username_pw_set(config_json["mqtt_user"],config_json["mqtt_pwd"])
if config_json["cert_location"] :
    mqtt_client.tls_set(config_json["cert_location"], tls_version=ssl.PROTOCOL_TLS)

# start event loop in background task and connect client
running = True
mqtt_loop()
mqtt_connect()

# Sensor initialization
while sensor_init == 0:
	try:
		sensor = py_qmc5883l.QMC5883L(output_range=py_qmc5883l.RNG_8G)
		sensor_init = 1
		log("Sensor init done")
		# print("Sensor init done")
	except OSError as error:
		log(error)
		time.sleep(5)


# Start measure
ticks = 0
last_count_tick = -10
try :
    while True:
        try:
            m = sensor.get_data()
            read_success += 1
            ticks += 1
            if m[1] < normal - hysteresis:
                if state == "init":
                    state = "count"
                if state == "idle":
                    ticks_between = ticks - last_count_tick
                    if(ticks_between > tick_idle_interval):
                        state = "count"
                        log("Count start at " + str(m))
                        gas_meter_minute += 10
                        gas_meter_day += 10
                        gas_meter_month += 10
                        gas_meter_year += 10
                        gas_meter_total += 10
                        last_count_tick = ticks
                    else:
                        log("Reject count due to short timeframe " + str(ticks_between))
            if m[1] > normal:
                if state == "init":
                    state = "idle"
                if state == "count":
                    log("Count end at   " +str(m))
                    state = "idle"
                    last_count_tick = ticks
        except OSError as error:
            log(error)
            read_fail += 1 
                         
        if loop_counter >= loop_time:
    		# check each minute for new day / month / year
            tod = datetime.today().date()
            if(last_sensor_date.day != tod.day) :
                log("Day Switch")
                gas_meter_day = 0
                # day reset of success counter
                read_fail = 0
                read_success = 0
                if(last_sensor_date.month != tod.month) :
                    log("Month Switch")
                    gas_meter_month = 0
                    if(last_sensor_date.year != tod.year) :
                        log("Year Switch")
                        gas_meter_month = 0
            last_sensor_date = datetime.today().date()
            if read_success == 0:
                success_rate = 0.0
            else:
                success_rate = round(100.0 - (float(read_fail) * 100 / float(read_success)),1)
    
            publish()
    		# reset loop counter and minutely consumption
            loop_counter = 1
            gas_meter_minute = 0
    	# increase loop counter and sleep
        loop_counter = loop_counter + read_interval
        time.sleep(read_interval)
  
# catches nearly all possible exceptions      
except Exception as e:
    log(traceback.format_exc())

# in case of fall through to this point: stop event loop and write current data into file
finally :
    log("final exit")
    running = False
    f = open(execution_path+"/data.json", "w")
    f.write(json.dumps(data_json))
    f.close()   
    
