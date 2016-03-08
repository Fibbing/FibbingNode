# FibbingNode
This repository contains the code to run a fibbing controller
that is able to control unmodified OSPF router to setup arbitrary paths in the network.

The controller is currently compatible only with python 2.

The controller code is split into 3 main parts:

1. The [Quagga](https://github.com/Fibbing/Quagga) directory, that contains a modified version of quagga that is able to craft
and flood arbitrary Type-5 LSA which are used to inject the lies in the network.
2. The Southbound controller, the [fibbingnode](https://github.com/Fibbing/FibbingNode/tree/master/fibbingnode) python module, that will control the quagga ospfd instances
and trigger the injection/removal of these LSAs, as well as infer the current network topology
and decide whether the current instance of the controller is the 'master' one in case multiple controllers are
present in the network. A critical file to tune is the config file, whose defaults are specified in [fibbingnode/res/default.cfg](https://github.com/Fibbing/FibbingNode/blob/master/fibbingnode/res/default.cfg).It can then be run via 
```bash
python2 -m fibbingnode
```
3. The Northbound controller, [fibbingnode/shapeshifter](https://github.com/Fibbing/FibbingNode/tree/master/fibbingnode/algorithms)
which implements the algorithms to compute the augmented topology and then communicates to the
southern part through a json insterface.

# Basic installation

```bash
git clone --recursive https://github.com/Fibbing/FibbingNode.git
./install.sh
```

This will install the quagga distribution under /opt/fibbing/ and the fibbingnode python module

# Demo

[Sample labs are available in another repository](https://github.com/Fibbing/labs)

# Virtual-Machine

[Script to build a Virtual Box VM able to run the controller, make it interact with physical routers, or run mininet-based experiments is available in another repository](https://github.com/Fibbing/virtual-machine)

# Documentation

There is an ongoing work to document the inner-workings of the controller, its architecture, ... while not yet public, feel free to contact [@oliviertilmans](https://github.com/oliviertilmans) if you have questions.
