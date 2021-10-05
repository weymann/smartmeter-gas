# Smart Gasmeter

If you have an *old-style* gasmeter to measure gas consumption it's still possible to turn it into s smart device.

## Pre-conditions

* basic solder skills
* Raspberry Pi with free connectors
* MQTT Server

## Hardware

The software works on the hardware of the [magnetic sensor QMC5883L](https://www.google.com/search?q=QMC5883L&rlz=1C1ONGR_deDE951DE951&oq=QMC5883L). Find [assembly instructions in german](https://tutorials-raspberrypi.de/raspberry-pi-kompass-selber-bauen-hmc5883l/) or [here in english version](https://www.electronicwings.com/raspberry-pi/triple-axis-magnetometer-hmc5883l-interfacing-with-raspberry-pi).

**Note:** The above Tutorials are referencing the HMC5883L hardware from Honeywell while this software takes care for QMC5883L - the chinese version of the chip. For hardware assembly this makes no difference but software will differ!

Before running this Software you need to check hardware is basically working:

```
[03:13:20] openhabian@openhab:~$ i2cdetect -y 1
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:          -- -- -- -- -- -- -- -- -- -- 0d -- --
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
40: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
60: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
70: -- -- -- -- -- -- -- --

```

## Software

The software is written in python3. If 
```
python3 --version
```
returns a valid result you're fine. Otherwise [follow the install instructions](https://docs.python-guide.org/starting/install3/linux/)

Now clone the repo to your desired directory
```
git clone https://github.com/weymann/smartmeter-gas.git
```

### Dependencies

Install the needed python modules to enable hardware access plus distributing data via MQTT

* [QMC5883L python driver](https://github.com/RigacciOrg/py-qmc5883l)
* [Paho MQTT](https://www.eclipse.org/paho/index.php?page=clients/python/index.php) for data distribution 

### Configuration

Stored in json file in the same directoy as the python script. Basically three sections needs to be configured:
* hardware configuration of values which shall trigger a count
* MQTT configuration to distribute data
* some technical data from your gas bill to calculate kwh consumption and pricing 
```
{
    "device_value_idle" : 5000,
    "device_value_hysteresis" : 3000,
    "mqtt_server" : "whereever.youwant.com",
    "mqtt_port" : 8883,
    "mqtt_user" : "user",
    "mqtt_pwd" : "password",
    "mqtt_topic" : "home/smartmeter/gas",
    "cert_location" : "/etc/ssl/certs/ca-certificates.crt",
    "z_number" : 0.955,
    "heating_value" : 10.308,
    "gas_price" : 0.0578,
    "gas_fee_month" : 6
}
```

### Check Data

<img src="./doc/MQTTExplorer.png" style="float: right; margin-right: 10px;" />


I use [MQTT Explorer](http://mqtt-explorer.com/) to check my IoT devices.

# Going further

Great! You turned an old fashioned gas meter which needs to be checked manually into a full fashioned auto reporting smart meter. 

Use now your data and put it into your favorite Smarthome Software. I use [openHAB](https://www.openhab.org/) which provides the capability to receive MQTT data.

<img src="./doc/openHAB-Panel.png" style="float: right; margin-right: 10px;" />
