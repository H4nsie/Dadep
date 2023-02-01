# Day Ahead Dynamic Energy Prices
#
# Author: H4nsie
#
# Version
# 1.0.0 - initial release - xmas 2022

# TODO

"""
<plugin key="DADEP" name="Day Ahead Dynamic Energy Prices (DADEP)" author="H4nsie" version="1.0.0" wikilink="http://www.domoticz.com/" externallink="https://github.com/H4nsie/DADEP">
    <description>
        <h2>Day Ahead Dynamic Energy Prices (DADEP)</h2><br/>
        <ul style="list-style-type:square">
            <li>To equest access to the Restful API, please register on the Transparency Platform (<a href="link">https://transparency.entsoe.eu/</a>), after that, send an email to transparency@entsoe.eu with “Restful API access” in the subject line. Indicate the email address you entered during registration in the email body. The ENTSO-E Helpdesk will make their best efforts to respond to your request within 3 working days.</li>
         </ul>
    </description>    
    <params>
        <param field="Username" label="API token ENTSOE " default="please enter ENTOE token" width="300px" required="true"/>
        <param field="Mode1" label="Color deviation (%)" default="10" width="100px" required="true"/>
        <param field="Mode2" label="Energy tax (per kWh)" default="0.12599" width="100px" required="true"/>
        <param field="Mode3" label="Handling fee (per kWh)" default="0.0024793" width="100px" required="true"/>
        <param field="Mode4" label="Tax (% per kWh)" default="21" width="100px" required="true"/>
        <param field="Mode5" label="Delivery fee (per month) " default="6.25" width="100px" required="true"/>
        <param field="Mode6" label="Log level" width="100px">
            <options>
                <option label="Normal" value="Normal" default="true" />
                <option label="Debug" value="Debug"/>
            </options>
        </param>        
    </params>
</plugin>
"""

import Domoticz
import requests
from datetime import datetime, timedelta
from lxml import objectify


class BasePlugin:
    enabled = False
    def __init__(self):
    

        self.freq = 4 #multiplier for Domoticz.Heartbeat (no need to update frequent)
        self.running = True # be able to disable this pugin until restart, on connection error.
        self.sessionId = ''
        self.dict_hourlyprices={} # init dict
        self.mean = 0 # mean value costs +- 10 hours
        self.entsoe_api_url = 'https://transparency.entsoe.eu/api'
        self.documentType = 'A44'
        self.in_domain = '10YNL----------L'
        self.out_domain = '10YNL----------L'
        



    def onStart(self):

        if Parameters["Mode6"] == "Debug":
            Domoticz.Debugging(2)
            DumpConfigToLog()
        else:
            Domoticz.Debugging(0)
            
        Domoticz.Debug("onStart called")   
        
        self.securityToken = Parameters["Username"]
        self.energiebelasting_stroom = float(Parameters["Mode2"])
        self.handlingfee_stroom = float(Parameters["Mode3"])
        self.btw = float(Parameters["Mode4"])/100 
        self.leverkosten_stroom = float(Parameters["Mode5"]) #per month
        self.colordeviation = float(Parameters["Mode1"])
                
        Domoticz.Log("Plugin has " + str(len(Devices)) + " devices associated with it.")

        # set Heartbeat and freq        
        Domoticz.Heartbeat(10)    
        self.beatcount = self.freq*5
        Domoticz.Debug("beatcount :" + str(self.beatcount))
        self.heartbeat = self.beatcount

        # create P1 usage device if not yet created
        if (len(Devices) == 0):
            Domoticz.Device(Name="Electricity price", Unit=1, Type=243, Subtype=33, Switchtype=3, Used=1, Options={'ValueQuantity': 'Price', 'ValueUnits': 'Ct'}, DeviceID='DAPEP_PRICE').Create()
            Domoticz.Debug("Device DAPEP_PRICE (unit 1) created")
            
            Domoticz.Device(Name="Electricity color ", Unit=2, Type=243, Subtype=19, Switchtype=0, Used=1 , DeviceID='DAPEP_COLOR').Create()
            Domoticz.Debug("Device DAPEP_COLOR (unit 2) created")

            Domoticz.Device(Name="Electricity next green ", Unit=3, Type=243, Subtype=19, Switchtype=0, Used=1 , DeviceID='DAPEP_NEXTCOLOR').Create()
            Domoticz.Debug("Device DAPEP_NEXTCOLOR (unit 3) created")
            
        #force=True new data from API at start
        _plugin.getData(True)   
            

    def getData(self, forcenow=False):
        
        
        # to not to make too many API calls, only call in specific minutes to update -- set forcenow=True to force (at startup)
        time_now = datetime.now()
        current_minute = time_now.strftime("%M")
        Domoticz.Debug(current_minute)
        if forcenow == False and not current_minute in ["00", "01", "16", "31", "46"]:
            Domoticz.Debug("Not calling API at this moment")
            return
        Domoticz.Debug("getData called")
                
        dayshistory = 2  # 2 days is sufficiant,  but...
        if forcenow:
            dayshistory = 5  # if at startup, please fill history logs.
        dateback = datetime.now() - timedelta(days=dayshistory)
        periodStart = dateback.strftime("%Y%m%d%H00")   
        
        tomorrow = datetime.now() + timedelta(hours=22) # we can set enddate to as far as tomorrow as ENTSOE stops xml at last available hours.
        periodEnd = tomorrow.strftime("%Y%m%d%H00")
        Domoticz.Debug("Period END: "+ periodEnd)
        
        get_entsoe_feed(self, periodStart, periodEnd)
               
        
        #determine MEAN values between t - 11h and t + 11h from dict
        start_hour = datetime.now() - timedelta(hours=11)
        self.mean=0
        for i in range(22):
            pointer_hour = start_hour.strftime("%Y-%m-%d %H:00:00")    #attention! minutes and secs are 0
            #Domoticz.Debug (pointer_hour)
            value = self.dict_hourlyprices[pointer_hour]
            #Domoticz.Debug (value)
            self.mean = self.mean + value
            start_hour = start_hour + timedelta(hours=1)
        self.mean = self.mean / 22
        Domoticz.Debug("Mean value: " + str(self.mean))
        
        
        #determine color / percentage from current costs to mean costs
        time_now = datetime.now()
        current_hour = time_now.strftime("%Y-%m-%d %H:00:00")    #attention! minutes and secs are 0
        current_price = self.dict_hourlyprices[current_hour] # get price from dict
        Domoticz.Debug("Current value: " + str(current_price))
        percentage_diff = round(((current_price - self.mean ) / self.mean ) *100 ,0)
        Domoticz.Debug("Percentage diff: "+str(percentage_diff))
        color ="BLUE"
        if percentage_diff > self.colordeviation:
            color = "RED"
        if percentage_diff < -(self.colordeviation):
            color = "GREEN"
        Domoticz.Debug("Current color: "+ color)
        UpdateDevice(2, 0, color)
        
        
        #determine next GREEN time
        nextgreen = 'No green available'
        for i in range(22):   # could be more hours than available in future but struct handles ok.
            start_hour = datetime.now() + timedelta(hours=i)
            pointer_hour = start_hour.strftime("%Y-%m-%d %H:00:00")    #attention! minutes and secs are 0
            if pointer_hour in self.dict_hourlyprices:
                value = self.dict_hourlyprices[pointer_hour]
                percentage_diff = round(((value - self.mean ) / self.mean ) *100 ,0)
                Domoticz.Debug('DEBUG: ' + pointer_hour + ' costs ' + str(value) + ' df: '+ str(percentage_diff))
                if percentage_diff < -(self.colordeviation):
                    nextgreentime = datetime.strptime(pointer_hour, "%Y-%m-%d %H:00:00")
                    Domoticz.Debug(nextgreentime.strftime("%H:00"))
                    nextgreen = nextgreentime.strftime("%H:00")
                    break
        UpdateDevice(3, 0, nextgreen)
        

    def onStop(self):
        Domoticz.Debug("onStop called")

    def onConnect(self, Connection, Status, Description):
        Domoticz.Debug("onConnect called")
        Domoticz.Debug("Status:" + str(Status))

    def onMessage(self, Connection, Data):
        Domoticz.Debug("onMessage called")
        Domoticz.Debug("Data:" + str(Data))

    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Debug("onCommand called for Unit " + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level))

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        Domoticz.Debug("Notification: " + Name + "," + Subject + "," + Text + "," + Status + "," + str(Priority) + "," + Sound + "," + ImageFile)

    def onDisconnect(self, Connection):
        Domoticz.Debug("onDisconnect called")

    def onHeartbeat(self):
        Domoticz.Debug("onHeartbeat called")
        if self.running == False:
            self.freq = 10 # increase interval while repeating error message:
            Domoticz.Error("Plugin not running. Please check parameters and LAN connection and restart plugin")
            return
        
        if self.heartbeat < self.beatcount:
            self.heartbeat = self.heartbeat + 1
            Domoticz.Debug("hearbeat:" + str(self.heartbeat))
        else:
            self.getData(False) # call getData on heartbeat, but do not (False) force update NOW.
            Domoticz.Debug("Do update")
            self.heartbeat = 0
            
        Domoticz.Debug("End heartbeat")



global _plugin
_plugin = BasePlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onStop():
    global _plugin
    _plugin.onStop()

def onConnect(Connection, Status, Description):
    global _plugin
    _plugin.onConnect(Connection, Status, Description)

def onMessage(Connection, Data):
    global _plugin
    _plugin.onMessage(Connection, Data)

def onCommand(Unit, Command, Level, Hue):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Hue)

def onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile):
    global _plugin
    _plugin.onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile)

def onDisconnect(Connection):
    global _plugin
    _plugin.onDisconnect(Connection)

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()
    
    

def UpdateDevice(Unit, nValue, sValue, TimedOut=0, AlwaysUpdate=False):
    # Make sure that the Domoticz device still exists (they can be deleted) before updating it 
    if (Unit in Devices):
        if (Devices[Unit].nValue != nValue) or (Devices[Unit].sValue != sValue) or (Devices[Unit].TimedOut != TimedOut):
            Devices[Unit].Update(nValue=nValue, sValue=str(sValue), TimedOut=TimedOut)
            Domoticz.Debug("Update device: {} {} {} ".format(str(nValue), str(sValue), str(Devices[Unit].Name)))
    return


def get_entsoe_feed(self, periodStart, periodEnd):

    # compose url for API request
    api_url = self.entsoe_api_url + '?in_Domain=' + self.in_domain + '&out_Domain=' + self.out_domain + '&documentType=' + self.documentType + '&securityToken=' + self.securityToken + '&periodStart=' + periodStart + '&periodEnd=' + periodEnd



    try:
        response = requests.Session().get(url=api_url)
        Domoticz.Debug("DEBUG: Retreiving " +api_url)
    except Exception as err:
        Domoticz.Debug("DEBUG: ConnectionException")
        Domoticz.Error("Error connecting to ENTSOE - Error: {}".format(err) )
        return


    Domoticz.Debug("Resonse " + str(response.status_code )  )

    if (response.status_code == 503):
        #Domoticz.Error("Error connecting. ENTOE s Service Temporarily Unavailable")
        Domoticz.Error("ENTSOE: Service Temporarily Unavailable")
        return
    
    if (response.status_code == 200):
        xml_text = objectify.fromstring(response.content)
        objectify.deannotate(xml_text, cleanup_namespaces=True)
        #dump(xml_text
        # if multiple TimeSeries
        
        #get current hour for updating device display
        time_now = datetime.now()
        current_hour = time_now.strftime("%Y-%m-%d %H:00:00")    #attention! minutes and secs are 0
        
        for mytimeseries in xml_text.TimeSeries:
            ##Domoticz.Debug( 'START TIMESERIE')
#           Domoticz.Debug(( 'Data for ' + mytimeseries.Period.timeInterval.start.text + ' till ' + mytimeseries.Period.timeInterval.end.text)
            startdate = mytimeseries.Period.timeInterval.start.text
            for myperiod in mytimeseries.Period:
                #print myperiod.timeInterval.text
                for myprices in myperiod.Point:
                    TIMEZONE=0   #todo
                    this_date = datetime.strptime(startdate, '%Y-%m-%dT%H:%MZ') + timedelta(hours=int(myprices.position)-TIMEZONE)   # 2023-01-03T23:00Z
                    # org this_date_string = this_date.strftime("%d-%b-%Y %H:%M")
                    this_date_string = this_date.strftime("%Y-%m-%d %H:%M:%S")
                    
                    price =  myprices.__getattr__('price.amount')  / 1000   # use __getattr__ because tag has period
                    total_cost = (self.energiebelasting_stroom + price + self.handlingfee_stroom) * (1+self.btw)
                    Domoticz.Debug( 'At ' + this_date_string + ' costs ' + str(price) + ' is total: ' + str(round(total_cost*100,0)))
             
             
                    # save values into dict for future reference
                    self.dict_hourlyprices.update( {this_date_string: total_cost*100})
                
                    #update the device
                    #sValue must 3 semicolon separated values, the last value being a date a space and a time ("%Y-%m-%d %H:%M:%S" format) to update last days history, for instance "123456;78;2019-10-03 14:55:00"
                    #YYYY-MM-DD HH:mm:ss expected
                    
                    UpdateDevice(Unit=1, nValue=0, sValue="-1;"+str(round(total_cost*100,0))+";"+this_date_string, TimedOut=0)
                    
                    #if running past current time, please update the device's display   
                    if ( current_hour == this_date_string ):
                        #after loop put current price in device
                        Domoticz.Debug( 'CURRENT HOUR FOUND:' + current_hour + ' costs '+ str(round(total_cost*100,0)))
                        UpdateDevice(Unit=1, nValue=0, sValue="-1;"+str(round(total_cost*100,0)), TimedOut=0)      #adjust round to get more precise price




# Generic helper functions
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug( "'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    return
    
    
    
    
    





