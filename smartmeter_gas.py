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

host = ''
token = ''
upper_bound = 0
lower_bound = 0
read_interval = 1
sensor_init = 0
state = 'init'
loop_counter = 1
loop_time = 60
read_success = 0
read_fail = 0
success_rate = 0.0
execution_path = ""
mqtt_connected = False
mqtt_client = None
mqtt_topic = ""
kwh_calculation = False
kwh_factor = 0
price_calculation = False
price_factor = 0
days_in_month = 0

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))# get an instance of the logger object this module will use


def mqtt_connect():
    log("MQTT Client connect")
    global mqtt_client
    global mqtt_topic
    mqtt_client = mqtt.Client(client_id='SmartmeterGas', clean_session=True, userdata=None, protocol=mqtt.MQTTv311, transport="tcp")
    # MQTT Client setup
    mqtt_topic = config_json["mqtt_topic"]
    #mqtt_client.on_log = on_log
    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.on_message = on_message
    mqtt_client.on_subscribe = on_subscribe
    # mqtt_client.on_publish = on_publish


    if config_json["mqtt_user"] : 
        mqtt_client.username_pw_set(config_json["mqtt_user"],config_json["mqtt_pwd"])
    if config_json["cert_location"] :
        mqtt_client.tls_set(config_json["cert_location"], tls_version=ssl.PROTOCOL_TLS)

    # start event loop in background task and connect client
    mqtt_client.loop_start()   
    mqtt_client.connect(config_json["mqtt_server"],config_json["mqtt_port"])

def publish():
    # log("Publish Connected? "+str(mqtt_connected)+", Total: " + str(data_json["total"]))
    global mqtt_connected
    if not(mqtt_connected):
        mqtt_connect()
           	
    # pick total counter publish as total reult for this function
    # if it fails try to reconnect
    tc_result = mqtt_client.publish(mqtt_topic+"/total", data_json["total"],2,True)
    if tc_result[0] != 0:
        log("Publish failed "+str(tc_result))
        mqtt_connected = False
        # wait for next publish loop to reconnect
        return

    mqtt_client.publish(mqtt_topic+"/timestamp",datetime.now().isoformat(),2,True)
    mqtt_client.publish(mqtt_topic+"/success-rate",data_json["sucess_rate"],2,True)

    mqtt_client.publish(mqtt_topic+"/day/count", data_json["day"]["count"],2,True)
    mqtt_client.publish(mqtt_topic+"/month/count",data_json["month"]["count"],2,True)
    mqtt_client.publish(mqtt_topic+"/year/count",data_json["year"]["count"],2,True)
    if kwh_calculation :
        mqtt_client.publish(mqtt_topic+"/day/kwh", round(data_json["day"]["count"] * kwh_factor,3),2,True)
        mqtt_client.publish(mqtt_topic+"/month/kwh", round(data_json["month"]["count"] * kwh_factor,3),2,True)
        mqtt_client.publish(mqtt_topic+"/year/kwh", round(data_json["year"]["count"] * kwh_factor,3),2,True)
        # EXPERIMENTAL: for year split price into heating water circle (hwc), heating circle (hc) and fees
        if data_json["hwc-baseload"]:
            hwc_baseload = last_sensor_date.month * data_json["hwc-baseload"]
            hc_load = data_json["year"]["count"] - hwc_baseload
            mqtt_client.publish(mqtt_topic+"/year/kwh-hwc", round(hwc_baseload * kwh_factor,3),2,True)
            mqtt_client.publish(mqtt_topic+"/year/kwh-hc", round(hc_load * kwh_factor,3),2,True)
    
    if price_calculation :
        # breakdown gas fee to daily share
        day_gas_price = data_json["day"]["count"] * price_factor
        day_fee = config_json["gas_fee_month"] / days_in_month
        mqtt_client.publish(mqtt_topic+"/day/price", round(day_gas_price + day_fee, 2) ,2, True)
        mqtt_client.publish(mqtt_topic+"/day/price-gas",  round(day_gas_price, 2) ,2, True)
        mqtt_client.publish(mqtt_topic+"/day/price-fee",  round(day_fee, 2) ,2, True)

        month_gas_price = data_json["month"]["count"] * price_factor
        month_fee = config_json["gas_fee_month"]
        mqtt_client.publish(mqtt_topic+"/month/price", round( month_gas_price + month_fee,2),2,True)
        mqtt_client.publish(mqtt_topic+"/month/price-gas",  round(month_gas_price, 2) ,2, True)
        mqtt_client.publish(mqtt_topic+"/month/price-fee",  round(month_fee, 2) ,2, True)

        year_price = data_json["year"]["price-gas"] + data_json["year"]["price-fee"]
        mqtt_client.publish(mqtt_topic+"/year/price", round(year_price,2),2,True)
        mqtt_client.publish(mqtt_topic+"/year/price-gas", round(data_json["year"]["price-gas"], 2) ,2, True)
        mqtt_client.publish(mqtt_topic+"/year/price-fee", round(data_json["year"]["price-fee"],2),2,True)

        # EXPERIMENTAL: for year split price into heating water circle (hwc), heating circle (hc) and fees
        if data_json["hwc-baseload"]:
            hwc_baseload = last_sensor_date.month * data_json["hwc-baseload"]
            hc_load = data_json["year"]["count"] - hwc_baseload
            mqtt_client.publish(mqtt_topic+"/year/price-hwc", round(hwc_baseload * price_factor,2),2,True)
            mqtt_client.publish(mqtt_topic+"/year/price-hc", round(hc_load * price_factor,2),2,True)

# write current measured data into file
@background.task
def write_data():
    # write data file for persistent storage
    data_file = execution_path+"/data.json"
    log("Write data file "+data_file)
    with open(data_file, 'w') as json_file:
        json.dump(data_json, json_file)
        
# write configuration into file
@background.task
def write_config():
    # write data file for persistent storage
    config_file = execution_path+"/config.json"
    log("Write config file " + config_file)
    with open(config_file, 'w') as json_file:
        json.dump(config_json, json_file)

# log message towards systemd (started as service) plus command line (started manually)
def log(message):
	logging.info(message)

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

        # Before subscribing to "total counter" publish the last value from data file
        # otherwise retained "old" value uis posted and measurement is 
        log("Publish total " + str(data_json["total"]))        
        rc = mqtt_client.publish(mqtt_topic+"/total", data_json["total"],2,True) 
        log("Publish return code: "+str(rc))
        # subscribe for changes of "total counter" and config
        mqtt_client.subscribe(mqtt_topic+"/total", qos=0)
        mqtt_client.subscribe(mqtt_topic+"/config/#", qos=0)
        
    else:
        log("Failed to connect, return code %d", rc)

def on_disconnect(client, userdata, rc):
	global mqtt_connected
	mqtt_connected = False

def on_log(client, userdata, level, buf):
    logging.info(buf)

#def on_publish(client, userdata, mid):
#    log("on_publish: " + str(client) + " / " + str(userdata) + " / " + str(mid))

#define callbacks
def on_message(client, userdata, message):
    payload = str(message.payload.decode("utf-8"))
    # log("message received  " + payload +" topic" + message.topic)
    if message.topic == mqtt_topic+"/total" :
        # adapt all values according new current counter setting
        total_counter_received = int(payload)
        if(total_counter_received != data_json["total"]):
            delta = total_counter_received - data_json["total"]
            log("Received different total count, delta " + str(delta))
            data_json["total"] = total_counter_received
            data_json["day"]["count"] += delta
            data_json["month"]["count"] += delta
            data_json["year"]["count"] += delta
            if price_calculation:
                data_json["year"]["price-gas"] += delta * price_factor
            write_data()
    elif message.topic.startswith(mqtt_topic+"/config") :
        try:
            value = float(payload)
            if message.topic == mqtt_topic+"/config/heating-value":
                if config_json["heating_value"] != value:
                    config_json["heating_value"] = value
                    write_config()
            elif message.topic == mqtt_topic+"/config/z-number":
                if config_json["z_number"] != value:
                    config_json["z_number"] = value
                    write_config()
            elif message.topic == mqtt_topic+"/config/gas-price":
                if config_json["gas_price"] != value:
                    config_json["gas_price"] = value
                    write_config()
            elif message.topic == mqtt_topic+"/config/gas-fee":
                if config_json["gas_fee_month"] != value:
                    config_json["gas_fee_month"] = value
                    write_config()
            else:
                log("Topic "+message.topic+" not found in config")
        except ValueError:
            log("Payload "+payload+" isn't a number value")

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


mqtt_connect()

sensor = sensor_initialization()

# Start measure
last_count_tick = -10
measure_values = []
# catch anything during execution for clean finish
# e.g. Keyboard interrupt
try :
    counter_changed = False
    while True:
        read_error = False
        # catch device errors
        try:
            m = sensor.get_data()
            measure_values.append(m[device_measure_field])
            if len(measure_values) > 25:
                del measure_values[0]
            read_success += 1
            if m[device_measure_field] < lower_bound:
                if state == "init":
                    state = "count"
                if state == "idle":
                    state = "count"
                    log("Count start at " + str(measure_values))
                    data_json["day"]["count"] += 10
                    data_json["month"]["count"] += 10
                    data_json["year"]["count"] += 10
                    # due to possible gas / fee price changes during the year the values 
                    # are calculated directly in the counter
                    if price_calculation:
                        data_json["year"]["price-gas"] += 10 * price_factor
                    data_json["total"] += 10
                    counter_changed = True
            if m[device_measure_field] > upper_bound:
                if state == "init":
                    state = "idle"
                if state == "count":
                    log("Count end at   " + str(measure_values))
                    state = "idle"
        except OSError as error:
            # log(error)
            read_error = True
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
                    data_json["year"]["price-fee"] += config_json["gas_fee_month"]
                    
                    if(last_sensor_date.year != tod.year) :
                        log("Year Switch")
                        mqtt_client.publish(mqtt_topic+"/previous-year/count", data_json["year"]["count"],2,True)
                        if kwh_calculation :
                            mqtt_client.publish(mqtt_topic+"/previous-year/kwh", round(data_json["year"]["count"] * kwh_factor,3),2,True)
                            if price_calculation :
                                mqtt_client.publish(mqtt_topic+"/previous-year/price", round(data_json["year"]["count"] * price_factor,2),2,True)
                        data_json["year"]["count"] = 0
                        data_json["year"]["price"] = 0
                        data_json["year"]["price-gas"] = 0
                        data_json["year"]["price-fee"] = config_json["gas_fee_month"]
            
            last_sensor_date = datetime.today().date()
            if read_success == 0:
                data_json["sucess_rate"] = 0.0
            else:
                data_json["sucess_rate"] = round(100.0 - (float(read_fail) * 100 / float(read_success)),1)

            begin_publish = time.perf_counter_ns()
            if counter_changed :
                write_data()
                counter_changed = False

            publish() 
            end_publish = time.perf_counter_ns()
            loop_counter = 1

            # calculate duration in ms
            # if publish takes more than 50 ms log entry is added
            duration = (end_publish - begin_publish) / 1000000
            if duration > 50:
                log("Publish took " + str(duration) + "ms")
    	
        # increase loop counter and sleep for interval in case of successful read
        # otherwise wait only 100 ms for fast retry not to miss any count
        if not read_error:
            loop_counter += read_interval
            time.sleep(read_interval)
        else:
            time.sleep(0.1)

# catches nearly all possible exceptions      
except Exception as e:
    log(str(e))

# in case of fall through to this point: stop event loop and write current data into file
finally :
    log("final exit")
    mqtt_client.loop_stop()
    
log("normal exit")
mqtt_client.loop_stop()

