"""Deterministic collision-respecting paths for engine-owned tile movement."""
import heapq
from itertools import count
from .field import WATER
class PathNotFound(ValueError): pass

class ReachabilityTree:
    """One lazy directed Dijkstra search, reusable for many local destinations.

    Source forced steps and surfing transitions remain weighted edges. The
    search order matches independent shortest_path calls; no cross-observation
    cache or mutable world state is retained.
    """
    def __init__(self, game_map, start, blocked=(), surfing=False):
        self.game_map=game_map;self.start=tuple(start);self.blocked=set(blocked)
        if not game_map.is_walkable(*self.start):raise PathNotFound('start is blocked')
        self.initial=(self.start,bool(surfing));self.order=count()
        self.queue=[(0,next(self.order),self.initial)];self.costs={self.initial:0}
        self.previous={self.initial:None};self.segments={};self.settled={}

    def path_to(self,goal):
        goal=tuple(goal);m=self.game_map
        if not m.is_walkable(*goal) or goal in self.blocked:raise PathNotFound('destination is blocked')
        while goal not in self.settled and self.queue:
            cost,_,node=heapq.heappop(self.queue)
            if self.costs[node]!=cost:continue
            point,on_water=node
            self.settled.setdefault(point,node)
            for direction in ('north','west','east','south'):
                segment=m.step_path(point,direction,surfing=on_water)
                if not segment or any(p in self.blocked for p in segment):continue
                nxt=segment[-1];continued=on_water and int(m.cells.get(nxt,{}).get('behavior',0)) in WATER
                successor=(nxt,continued);new_cost=cost+len(segment)
                if new_cost<self.costs.get(successor,float('inf')) and nxt not in self.blocked and m.is_walkable(*nxt):
                    self.costs[successor]=new_cost;self.previous[successor]=node;self.segments[successor]=segment
                    heapq.heappush(self.queue,(new_cost,next(self.order),successor))
        node=self.settled.get(goal)
        if node is None:raise PathNotFound('no walkable route to destination')
        path=[]
        while node!=self.initial:path.append(self.segments[node]);node=self.previous[node]
        return [point for segment in reversed(path) for point in segment]

def shortest_path(game_map,start,goal,blocked=(),surfing=False):
    return ReachabilityTree(game_map,start,blocked,surfing).path_to(goal)
