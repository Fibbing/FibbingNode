import sys
import os
import re


if(len(sys.argv) < 4):
	print "usage: python script input_file ['city'|'continent'] ['pop'|'backbone']"

f = open(sys.argv[1])

t = sys.argv[2]
if(t!="city" and t!="continent"):
	print "Error: unknown options for conversion to entf. The only two known options are city and continent"
	sys.exit(-1)

area_inter_abr_link = sys.argv[3]
if(area_inter_abr_link!="pop" and area_inter_abr_link!="backbone"):
	print "Error: unknown options for conversion to entf. The only two known options are pop and backbone"
	sys.exit(-1)


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
    'Townsville': 'AS',
    'Brisbane': 'AS',
    'Darwin': 'AS',
    'Adelaide': 'AS',
    'Perth': 'AS',
    'Wellington': 'AS',
    'Albany': 'AS',
    'Melbourne': 'AS',
    'Victor+Harbour': 'AS',
    'Ballarat': 'AS',
    'Nuriootpa': 'AS',
    'Rockhampton': 'AS',
    'Bathurst': 'AS',
    'Penrith': 'AS',
    'Bendigo': 'AS',
    'Mount+Gambier': 'AS',
    'Newcastle': 'AS',
    'Gosford': 'AS',
    'Canberra': 'AS',
    'Murray+Bridge': 'AS',
    'Port+Pirie': 'AS',
    'Port+Lincoln': 'AS',
	'Bracknell': 'EU',
	'Geneva': 'EU',
	'Antwerp': 'EU',
	'Dusseldorf': 'EU',
	'Barcelona': 'EU',
	'Bratislava': 'EU',
	'Berlin': 'EU',
	'Rome': 'EU',
	'Manchester': 'EU',
	'Rotterdam': 'EU',
	'Prague': 'EU',
	'Vienna': 'EU',
	'Stuttgart': 'EU',
	'Nuremberg': 'EU',
	'Dresden': 'EU',
	'Genoa': 'EU',
	'Cagliari':'EU',
	'Chemnitz':'EU',
	'Oslo':'EU',
	'Firenze':'EU',
	'Pisa':'EU',
	'Cosenza':'EU',
	'Salerno':'EU',
	'Madrid':'EU',
	'Bergamo':'EU',
	'Mannheim':'EU', 
	'Alessandria':'EU', 
	'Mainz':'EU', 
	'Zurich':'EU', 
	'Offenbach':'EU', 
	'Torino':'EU', 
	'Pescara':'EU', 
	'Venice':'EU', 
	'Basel':'EU', 
	'Darmstadt':'EU', 
	'Modena':'EU', 
	'Ancona':'EU', 
	'Bologna':'EU', 
	'Bari':'EU', 
	'Karlsruhe':'EU', 
	'Padova':'EU',
	'Toronto':'US', 
	'Jersey+City':'US', 
	'Herndon':'US', 
	'Fort+Worth':'US', 
	'Austin':'US', 
	'Tukwila':'US', 
	'Irvine':'US', 
	'Miami':'US', 
	'El+Segundo':'US', 
	'Weehawken':'US', 
	'Palo+Alto':'US', 
	'Waltham':'US', 
	'Oak+Brook':'US',
	'San+Francisco':'US', 
	'IAD':'US', 
	'Newark':'US', 
	'Kahului':'US', 
	'Napa':'US', 
	'San+Carlos':'US'
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

error_found = False
not_found = set()

abrs = {}
topology = []
not_found = set()

for line in f:
    s = line.split()
    
    res0 = get_match(s[0])
    check_res(res0)
    
    res1 = get_match(s[1])
    check_res(res1)
    
    weight = float(s[2])*10
   
    if t=="continent":    
    ## Map on continent
		try:
			if(pops_mapping[res0]!=pops_mapping[res1]):
				abrs[s[0]] = True
				abrs[s[1]] = True
			topology.append((s[0], pops_mapping[res0], s[1], pops_mapping[res1], weight))
		except KeyError:
			try:
				pops_mapping[res0]
			except KeyError:
				not_found.add(res0)
			try:
				pops_mapping[res1]
			except KeyError:
				not_found.add(res1)
    if t=="city":
    ## Map on cities
		if res0!=res1:
			abrs[s[0]] = True
			abrs[s[1]] = True
		topology.append((s[0], res0, s[1], res1, weight))

for link in topology:
	rid1 = link[0]
	mapping1 = link[1]
	rid2 = link[2]
	mapping2 = link[3]
	weight = link[4]
	
	if mapping1==mapping2:
		if rid1 in abrs and rid2 in abrs:
			if area_inter_abr_link=="pop":
				print "%s %s %d %s" % (rid1, rid2, weight, mapping1)
			else:
				print "%s %s %d %s" % (rid1, rid2, weight, backbone)
		else:
			print "%s %s %d %s" % (rid1, rid2, weight, mapping1)
	else:
		print "%s %s %d %s" % (rid1, rid2, weight, backbone)

if not_found:
	print not_found
f.close()