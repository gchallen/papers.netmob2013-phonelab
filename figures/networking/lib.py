#!/usr/bin/env python

import re, cPickle, argparse, datetime

from common import lib
from location.lib import DeviceLocation

class Networking:
  
  @classmethod
  def load(cls, path):
    return cPickle.load(open(path, 'rb'))
  
  def __init__(self, path):
    self.path = path
    self.tags = ['PhoneLabSystemAnalysis-Telephony', 'PhoneLabSystemAnalysis-Wifi', 'PhoneLabSystemAnalysis-Location', 'PhoneLabSystemAnalysis-Snapshot']
    self.devices = set([])
    
    self.data_sessions = []
    self.data_usage = []
    
  def process(self, time_limit=None):
    
    wifi_states = {}
    threeg_states = {}
    traffic_states = {}
    
    for logline in lib.LogFilter(self.tags).generate_loglines(time_limit=time_limit):
      self.devices.add(logline.device)
      if logline.log_tag == 'PhoneLabSystemAnalysis-Telephony' and logline.json.has_key('State'):
        if logline.json['State'] == 'DATA_CONNECTED':
          if threeg_states.has_key(logline.device):
            continue
          threeg_states[logline.device] = ThreeGSession(logline)
        elif logline.json['State'] == 'DATA_DISCONNECTED':
          if not threeg_states.has_key(logline.device):
            continue
          else:
            threeg_states[logline.device].end = logline.datetime
            self.data_sessions.append(threeg_states[logline.device])
            del(threeg_states[logline.device])
      elif logline.log_tag == 'PhoneLabSystemAnalysis-Wifi' and logline.json != None and logline.json.has_key('State'):
        if logline.json['State'] == 'CONNECTED':
          if wifi_states.has_key(logline.device):
            if wifi_states[logline.device].bssid == WifiSession.get_bssid(logline):
              continue
          wifi_states[logline.device] = WifiSession(logline)
        elif logline.json['State'] == 'DISCONNECTED':
          if not wifi_states.has_key(logline.device):
            continue
          else:
            wifi_states[logline.device].end = logline.datetime
            self.data_sessions.append(wifi_states[logline.device])
            del(wifi_states[logline.device])
      elif logline.log_tag == 'PhoneLabSystemAnalysis-Location' and logline.json != None \
        and logline.json.has_key('Action') and logline.json['Action'] == 'edu.buffalo.cse.phonelab.LOCATION_UPDATE':
        
        if wifi_states.has_key(logline.device):
          wifi_states[logline.device].locations.append(DeviceLocation(logline))
        if threeg_states.has_key(logline.device):
          threeg_states[logline.device].locations.append(DeviceLocation(logline))
      elif logline.log_tag == 'PhoneLabSystemAnalysis-Snapshot' and logline.json != None and logline.json.has_key('Taffic'):     
        if not traffic_states.has_key(logline.device):
          traffic_states[logline.device] = TrafficState(logline.device)
        usages = traffic_states[logline.device].update(logline)
        if usages != None:
          self.data_usages += usages
          
      
  def dump(self):
    cPickle.dump(self, open(self.path, 'wb'), cPickle.HIGHEST_PROTOCOL)

class TrafficState(object):
  TRAFFIC_PATTERN = re.compile(r"""Type:\s*(?P<type>\w+), Rx:\s*(?P<rx>\d+), Tx:\s*(?P<tx>\d+)""")
  
  def __init__(self, device):
    self.device = device
    self.last_update = None
    
    self.last_threeg_tx = None
    self.last_threeg_rx = None
    self.threeg_rx_diff = 0
    self.threeg_tx_diff = 0
   
    self.last_total_tx = None
    self.last_total_rx = None
    self.total_rx_diff = 0
    self.total_tx_diff = 0
  
  def update(self, logline):
    traffic_match = TrafficState.TRAFFIC_PATTERN.search(logline.log_message)
    if traffic_match == None:
      return
    usages = None
    if self.last_update != None and logline.datetime > self.last_update:
      usages = [NetworkUsage(self.device, self.last_update, logline.datetime, self.threeg_rx_diff, self.threeg_tx_diff, False),
                NetworkUsage(self.device, self.last_update, logline.datetime, (self.total_rx_diff - self.threeg_rx_diff), (self.total_tx_diff - self.threeg_tx_diff), True),]
      
    if traffic_match.group('type') == 'mobile':
      if self.last_threeg_tx != None:
        self.threeg_tx_diff = int(traffic_match.group('tx')) - self.last_threeg_tx
        if self.last_threeg_tx != int(traffic_match.group('tx')):
          self.threeg_update = logline.datetime
      if self.last_threeg_rx != None:
        self.threeg_rx_diff = int(traffic_match.group('rx')) - self.last_threeg_rx
        if self.last_threeg_rx != int(traffic_match.group('rx')):
          self.threeg_update = logline.datetime
      
      self.last_threeg_tx = int(traffic_match.group('tx'))
      self.last_threeg_rx = int(traffic_match.group('rx'))
    
    return usages
  
class NetworkSession(object):
  def __init__(self, logline):
    self.device = logline.device
    self.start = logline.datetime
    self.end = None
    self.locations = []

class WifiSession(NetworkSession):
  BSSID_PATTERN = re.compile(r"""BSSID:\s*(?P<bssid>[A-Fa-f0-9:]+),""")
  
  def __init__(self, logline):
    super(WifiSession, self).__init__(logline)
    self.bssid = WifiSession.get_bssid(logline)
    
  @classmethod
  def get_bssid(cls, logline):
    return WifiSession.BSSID_PATTERN.search(logline.log_message).group('bssid')

class ThreeGSession(NetworkSession):
  def __init__(self, logline):
    super(ThreeGSession, self).__init__(logline)

class NetworkUsage(object):
  def __init__(self, device, rx, tx, start, end, is_wifi):
    self.device = device
    self.start = start
    self.end = end
    self.rx = rx
    self.tx = tx
    self.is_wifi = is_wifi
    
    if self.rx < 0 or self.tx < 0:
      raise Exception("Negative RX or TX for NetworkUsage object.") 
    
if __name__=="__main__":
  parser = argparse.ArgumentParser()
  parser.add_argument("--time_limit_hours", help="Hours to process.",
                    action='store', type=int, default=None)
  args = parser.parse_args()
  
  time_limit = None
  if args.time_limit_hours != None:
    time_limit = datetime.timedelta(hours=args.time_limit_hours)
  
  t = Networking('data.dat')
  t.process(time_limit=time_limit)
  t.dump()
