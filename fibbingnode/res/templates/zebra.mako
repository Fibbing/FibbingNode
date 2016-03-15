hostname ${node.hostname}
password ${node.password}
% if node.zebra.logfile:
log file ${node.zebra.logfile}
% endif
% for section in node.zebra.debug:
debug zebra section
% endfor
% for pl in node.zebra.prefixlists:
ip prefix-list ${pl.name} ${pl.action} ${pl.prefix} ge ${pl.ge}
% endfor
!
% for rm in node.zebra.routemaps:
route-map ${rm.name} ${rm.action} ${rm.prio}
% for prefix in rm.prefix:
match ip address prefix-list ${prefix}
% endfor
!
% for proto in rm.proto:
ip protocol ${proto} route-map ${rm.name}
% endfor
% endfor
!
% for prefix, via in node.zebra.static_routes:
ip route ${prefix} via ${via}
% endfor
