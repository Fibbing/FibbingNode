from fibbingnode import log as logger


def find_sink(dag):
    return [node for node in dag.nodes() if dag.out_degree(node) == 0]


def add_separate_destination_to_sinks(destination, input_topo, dag, cost=1):
    if destination in input_topo:
        destination = "Dest_" + destination
    for node in find_sink(dag):
        logger.debug("Connecting %s to %s with cost %d",
                     destination, node, cost)
        input_topo.add_edge(node, destination, weight=cost)
        dag.add_edge(node, destination)
    return destination
