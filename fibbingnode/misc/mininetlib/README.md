# Fibbing Mininet extensions

These are [Mininet](www.mininet.org) classes, and allow you to instantiate
network with autoconfigured OSPF routers, as well as place Fibbing controllers
around.

## Usage
Using these classes requires a working mininet installation

To install mininet:

```bash
pip install git+git://github.com/mininet/mininet.git
```

Or visit www.mininet.org

You can then use these classes by simply performing the following import
in your topology files:
```python
import fibbingnode.misc.mininetlib
```

You can find example topologies in
[Fibbing/labs](https://github.com/Fibbing/labs)
