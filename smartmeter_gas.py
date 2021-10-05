#!/usr/bin/python3

import py_qmc5883l
import paho.mqtt.client as mqtt
import paho.mqtt.publish as publish
import ssl
import json
import asyncio
import background
import logging
import os
import sys
import time
from datetime import datetime
from datetime import date
from calendar import monthrange
from systemd.journal import JournaldLogHandler

# Needed dependency:
# https://github.com/RigacciOrg/py-qmc5883l

host = ""
token = ''
upper_bound = 0
lower_bound = 0
read_interval = 2
measure_field = 1
tick_idle_interval = 3
sensor_init = 0
openhab_access = 0
state = "init"
loop_counter = 1
loop_time = 60
read_success = 0
read_fail = 0
success_rate = 0.0
execution_path = ""
mqtt_connected = False
mqtt_client = mqtt.Client(client_id='', clean_session=True, userdata=None, protocol=mqtt.MQTTv311, transport="tcp")
mqtt_topic = ""
kwh_calculation = False
kwh_factor = 0
price_calculation = False
price_factor = 0
days_in_month = 0

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))# get an instance of the logger object this module will use


@background.task
def mqtt_loop():
    mqtt_client.loop_start()
    #while running:
    #    mqtt_client.loop()
    #    time.sleep(1)
        

@background.task
def mqtt_connect():
  log("MQTT Client connect")
  connectionResult = mqtt_client.connect(config_json["mqtt_server"],config_json["mqtt_port"])

def publish():
    #global price_claculation
    global mqtt_connected
    global mqtt_topic
    log("Publish Connected? "+str(mqtt_connected)+", Total: " + str(data_json["total"]))
    if not(mqtt_connected):
        mqtt_connect()
           	
    mqtt_client.publish(mqtt_topic+"/timestamp",datetime.now().isoformat(),2,True)
    mqtt_client.publish(mqtt_topic+"/success-rate",data_json["sucess_rate"],2,True)
    mqtt_client.publish(mqtt_topic+"/total", data_json["total"],2,True)
    mqtt_client.publish(mqtt_topic+"/day/count", data_json["day"]["count"],2,True)
    mqtt_client.publish(mqtt_topic+"/month/count",data_json["month"]["count"],2,True)
    mqtt_client.publish(mqtt_topic+"/year/count",data_json["year"]["count"],2,True)
    if kwh_calculation :
        mqtt_client.publish(mqtt_topic+"/day/kwh", round(data_json["day"]["count"] * kwh_factor,3),2,True)
        mqtt_client.publish(mqtt_topic+"/month/kwh", round(data_json["month"]["count"] * kwh_factor,3),2,True)
        mqtt_client.publish(mqtt_topic+"/year/kwh", round(data_json["year"]["count"] * kwh_factor,3),2,True)
        # for year split price into heating water circle (hwc), heating circle (hc) and fees
        hwc_baseload = last_sensor_date.month * data_json["hwc-baseload"]
        hc_load = data_json["year"]["count"] - hwc_baseload
        mqtt_client.publish(mqtt_topic+"/year/kwh-hwc", round(hwc_baseload * kwh_factor,3),2,True)
        mqtt_client.publish(mqtt_topic+"/year/kwh-hc", round(hc_load * kwh_factor,3),2,True)
    
    if price_calculation :
        # for year split price into heating water circle (hwc), heating circle (hc) and fees
        hwc_baseload = last_sensor_date.month * data_json["hwc-baseload"]
        hc_load = data_json["year"]["count"] - hwc_baseload
        mqtt_client.publish(mqtt_topic+"/year/price-hwc", round(hwc_baseload * price_factor,2),2,True)
        mqtt_client.publish(mqtt_topic+"/year/price-hc", round(hc_load * price_factor,2),2,True)
        if config_json["gas_fee_month"] :
            # breakdown gas fee to daily share
            mqtt_client.publish(mqtt_topic+"/day/price", round(data_json["day"]["count"] * price_factor + config_json["gas_fee_month"] / days_in_month,2))
            mqtt_client.publish(mqtt_topic+"/month/price", round(data_json["month"]["count"] * price_factor + config_json["gas_fee_month"],2),2,True)
            mqtt_client.publish(mqtt_topic+"/year/price", round(data_json["year"]["count"] * price_factor + config_json["gas_fee_month"] * last_sensor_date.month,2),2,True)
            mqtt_client.publish(mqtt_topic+"/year/fees", round(config_json["gas_fee_month"] * last_sensor_date.month,2),2,True)
        else :
            mqtt_client.publish(mqtt_topic+"/day/price", round(data_json["day"]["count"] * price_factor,2))
            mqtt_client.publish(mqtt_topic+"/month/price", round(data_json["month"]["count"] * price_factor,2),2,True)
            mqtt_client.publish(mqtt_topic+"/year/price", round(data_json["year"]["count"] * price_factor,2),2,True)

@background.task
def write_data():
    # write data file for persistent storage
    log("Write data file "+execution_path)
    with open(execution_path+"/data.json", 'w') as json_file:
        json.dump(data_json, json_file)
        
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
        # Publish config parameters which can be modified
        if kwh_calculation:
            mqtt_client.publish(mqtt_topic+"/config/heating-value", config_json["heating_value"],2,True)
            mqtt_client.publish(mqtt_topic+"/config/z-number", config_json["z_number"],2,True)
        if price_calculation :
            mqtt_client.publish(mqtt_topic+"/config/gas-price",config_json["gas_price"],2,True)
            mqtt_client.publish(mqtt_topic+"/config/gas-fee",config_json["gas_fee_month"],2,True)
        subres = mqtt_client.subscribe(mqtt_topic+"/total", qos=0)
        log("Subsrciption result "+str(subres))
    else:
        log("Failed to connect, return code %d\n", rc)

def on_disconnect(client, userdata, flags, rc):
		global mqtt_connected
		mqtt_connected = False

def on_log(client, userdata, level, buf):
    logging.info(buf)

#define callbacks
def on_message(client, userdata, message):
    payload = str(message.payload.decode("utf-8"))
    log("message received  " + payload +" topic" + message.topic)
    if(message.topic == mqtt_topic+"/total"):
        total_counter_received = int(payload)
        if(total_counter_received != data_json["total"]):
            delta = total_counter_received - data_json["total"]
            log("Received different total count, delta " + str(delta))
            data_json["total"] = total_counter_received
            data_json["day"]["count"] += delta
            data_json["month"]["count"] += delta
            data_json["year"]["count"] += delta
        else:
            log("Received same total count")
    

def on_publish(client,userdata,result):
    log("data published "+str(result))
    pass

def on_subscribe(client, userdata, mid, granted_qos):
    log("subscribe feedback "+str(mid))

# Sensor initialization
def sensor_initialization():
    global sensor_init
    while sensor_init == 0:
	    try:
		    sensor = py_qmc5883l.QMC5883L(output_range=py_qmc5883l.RNG_8G)
		    sensor_init = 1
		    log("Sensor init done")
		    # print("Sensor init done")
	    except OSError as error:
		    log(error)
		    time.sleep(5)
    return sensor

# handle passed arguments
if len(sys.argv) > 1:
    if(str(sys.argv[1]) == "help"):
        print("Usage")
        print("help - this information")
        print("setup - test magnetic sensor data")
        sys.exit(0)        
    if(str(sys.argv[1]) == "setup"):
        sensor = sensor_initialization()
        while True:
            try:
                m = sensor.get_data()
                print(str(datetime.today()) +" "+str(m))
                time.sleep(1)
            except Exception as e:
                print(str(e))
                print("sleep and continue")
                time.sleep(1)
                # continue
        sys.exit(0)        
        
# program start
last_sensor_date = datetime.today().date()

# Read config file
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
        now = datetime.today().date()
        days_in_month = monthrange(now.year, now.month)[1]
        log("Price Factor " + str(price_factor))
    else :
        log("No price calculation")
else :
    log("No kwh calculation")
    
log(config_json)
 

# Read stored data file with last stored values
data_file = open(execution_path+"/data.json", "r")
data_json = json.loads(data_file.read())
log(data_json)

# set values for device driver
device_measure_field = config_json["device_measure_field"]
upper_bound = config_json["device_upper_bound"]
lower_bound = config_json["device_lower_bound"]


# MQTT Client setup
mqtt_topic = config_json["mqtt_topic"]
#mqtt_client.on_log = on_log
#mqtt_client.on_publish = on_publish
mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect
mqtt_client.on_message = on_message
mqtt_client.on_subscribe = on_subscribe


if config_json["mqtt_user"] : 
    mqtt_client.username_pw_set(config_json["mqtt_user"],config_json["mqtt_pwd"])
if config_json["cert_location"] :
    mqtt_client.tls_set(config_json["cert_location"], tls_version=ssl.PROTOCOL_TLS)

# start event loop in background task and connect client
running = True
mqtt_loop()
mqtt_connect()

sensor = sensor_initialization()

# Start measure
ticks = 0
last_count_tick = -10
try :
    counter_changed = False
    while True:
        try:
            m = sensor.get_data()
            read_success += 1
            ticks += 1
            if m[device_measure_field] < lower_bound:
                if state == "init":
                    state = "count"
                if state == "idle":
                    ticks_between = ticks - last_count_tick
                    if(ticks_between > tick_idle_interval):
                        state = "count"
                        log("Count start at " + str(m))
                        data_json["day"]["count"] += 10
                        data_json["month"]["count"] += 10
                        data_json["year"]["count"] += 10
                        data_json["total"] += 10
                        last_count_tick = ticks
                        counter_changed = True
                    else:
                        log("Reject count due to short timeframe " + str(ticks_between))
            if m[device_measure_field] > upper_bound:
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
    		# check for new day / month / year
            tod = datetime.today().date()
            if(last_sensor_date.day != tod.day) :
                log("Day Switch")
                mqtt_client.publish(mqtt_topic+"/yesterday/count", data_json["day"]["count"],2,True)
                if kwh_calculation :
                    mqtt_client.publish(mqtt_topic+"/yesterday/kwh", round(data_json["day"]["count"] * kwh_factor,3),2,True)
                    if price_calculation :
                        mqtt_client.publish(mqtt_topic+"/yesterday/price", round(data_json["day"]["count"] * price_factor,2),2,True)
                data_json["day"]["count"] = 0
                
                # day reset of success counter
                read_fail = 0
                read_success = 0
                if(last_sensor_date.month != tod.month) :
                    log("Month Switch")
                    mqtt_client.publish(mqtt_topic+"/previous-month/count", data_json["month"]["count"],2,True)
                    if kwh_calculation :
                        mqtt_client.publish(mqtt_topic+"/previous-month/kwh", round(data_json["month"]["count"] * kwh_factor,3),2,True)
                        if price_calculation :
                            mqtt_client.publish(mqtt_topic+"/previous-month/price", round(data_json["month"]["count"] * price_factor,2),2,True)
                    days_in_month = monthrange(tod.year, tod.month)[1]
                    data_json["month"]["count"] = 0
                    
                    if(last_sensor_date.year != tod.year) :
                        log("Year Switch")
                        mqtt_client.publish(mqtt_topic+"/previous-year/count", data_json["year"]["count"],2,True)
                        if kwh_calculation :
                            mqtt_client.publish(mqtt_topic+"/previous-year/kwh", round(data_json["year"]["count"] * kwh_factor,3),2,True)
                            if price_calculation :
                                mqtt_client.publish(mqtt_topic+"/previous-year/price", round(data_json["year"]["count"] * price_factor,2),2,True)
                        data_json["year"]["count"] = 0
            
            last_sensor_date = datetime.today().date()
            if read_success == 0:
                data_json["sucess_rate"] = 0.0
            else:
                data_json["sucess_rate"] = round(100.0 - (float(read_fail) * 100 / float(read_success)),1)
    
            if counter_changed :
                log("Write data request")
                write_data()
                counter_changed = False
            else :
                log("Nothing changed")
            publish()
            loop_counter = 1
    	# increase loop counter and sleep
        loop_counter = loop_counter + read_interval
        time.sleep(read_interval)
  
# catches nearly all possible exceptions      
except Exception as e:
    log(str(e))

# in case of fall through to this point: stop event loop and write current data into file
finally :
    log("final exit")
    running = False
    mqtt_client.loop_stop()
    
log("normal exit")
running = False
mqtt_client.loop_stop()

