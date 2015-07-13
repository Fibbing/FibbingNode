import sys
import os
import re

f = open(sys.argv[1])
regexp = "(.*?),.*"
regexp2 = "([a-zA-Z\+]*)[0-9]*"

backbone = 'BACKBONE'

pops_mapping = {
    'Amsterdam' : 'EU',
    'Anaheim' : 'US',
    'Atlanta' : 'US',
    'Boston' : 'US',
    'Brussels' : 'EU',
    'Cheyenne' : 'US',
    'Chicago' : 'US',
    'Copenhagen' : 'EU',
    'Dallas' : 'US',
    'Frankfurt' : 'EU',
    'Hamburg' : 'EU',
    'Hong+Kong' : 'AS',
    'Kansas+City' : 'US',
    'London' : 'EU',
    'Manasquan' : 'US',
    'Milan' : 'EU',
    'New+York' : 'US',
    'Orlando' : 'US',
    'Paris' : 'EU',
    'Pearl+Harbor' : 'US',
    'Pennsauken' : 'US',
    'Rancho+Cordova' : 'US',
    'Relay' : 'US',
    'Reston' : 'US',
    'Roachdale' : 'US',
    'San+Jose' : 'US',
    'Seattle' : 'US',
    'Springfield' : 'US',
    'Stockholm' : 'EU',
    'Stockton' : 'US',
    'Sydney' : 'AS',
    'Tacoma' : 'US',
    'Tokyo' : 'AS',
    'Washington' : 'US',
    'Research+Triangle+Park' : 'US',
    'Denver': 'US',
    'Lees+Summit': 'US',
    'Dublin': 'EU',
    'Los+Angeles': 'US',
    'Ashburn': 'US',
    'Munich' : 'EU',
    'Santa+Clara' : 'US',
    'Richardson': 'US',
    'Singapore': 'AS',
    'Townsville': 'AS'
}

def get_match(s):
    m = re.findall(regexp, s)
    if not m:
        m = re.findall(regexp2, s)
        if not m:
            return False
    return m[0]

def check_res(res):
    if res:
        pass
    else:
        print "Error while parsing line %s" % (line)
        sys.exit(-1)

for line in f:
    s = line.split()
    
    res1 = get_match(s[0])
    check_res(res1)
    
    res2 = get_match(s[1])
    check_res(res2)
    
    weight = float(s[2])*10
    
    ## Map on continent
    #if(pops_mapping[res1]==pops_mapping[res2]):
    #    print "%s %s %d %s" % (s[0], s[1], weight, pops_mapping[res1])
    #else:
    #    print "%s %s %d %s" % (s[0], s[1], weight, backbone)
    
    ## Map on cities
    if(res1==res2):
        print "%s %s %d %s" % (s[0], s[1], weight, res1)
    else:
        print "%s %s %d %s" % (s[0], s[1], weight, backbone)
f.close()