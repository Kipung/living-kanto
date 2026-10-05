import pytest
from living_kanto.simulation.maps import GameMap
from living_kanto.simulation.pathfinding import ReachabilityTree,PathNotFound

def test_lazy_search_resumes_after_previous_destination_and_preserves_ties():
    m=GameMap('test',5,3,['11111','10001','11111'],{})
    tree=ReachabilityTree(m,(0,1))
    assert tree.path_to((0,0))==[(0,0)]
    assert tree.path_to((4,1))==[(0,0),(1,0),(2,0),(3,0),(4,0),(4,1)]
    # Returned paths are independent; a caller cannot corrupt cached parents.
    first=tree.path_to((4,1));first.clear()
    assert len(tree.path_to((4,1)))==6
    with pytest.raises(PathNotFound):tree.path_to((2,1))
    assert tree.path_to((0,2))==[(0,2)]

def test_cache_does_not_bridge_disconnected_cells_after_search_exhaustion():
    m=GameMap('test',5,1,['11011'],{})
    tree=ReachabilityTree(m,(0,0))
    with pytest.raises(PathNotFound):tree.path_to((4,0))
    assert tree.path_to((1,0))==[(1,0)]
    with pytest.raises(PathNotFound):tree.path_to((3,0))
