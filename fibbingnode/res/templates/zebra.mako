hostname ${node.hostname}
password ${node.password}

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
