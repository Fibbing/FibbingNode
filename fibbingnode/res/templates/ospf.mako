hostname ${node.hostname}
password ${node.password}
!
% for intf in node.ospf.interfaces:
interface ${intf.name}
  # ${intf.description}
  # Highiest priority routers will be DR
  ip ospf priority ${intf.ospf.priority}
  ip ospf cost ${intf.ospf.cost}
  # dead/hello intervals must be consistent across a broadcast domain
  ip ospf dead-interval ${intf.ospf.dead_int}
  ip ospf hello-interval ${intf.ospf.hello_int}
!
% endfor
router ospf
  router-id ${node.ospf.router_id}
  !
  redistribute fibbing metric-type 1
  !
  % for net in node.ospf.networks:
  network ${net.domain} area ${net.area}
  % endfor
!