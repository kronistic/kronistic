
import math
from kron_app.mask_utils import PWlinear, PWfn, Edge, Topo

def test_PWfn_combine():
  m=PWfn(False, Edge(1), True, Edge(2.3), False)
  n=PWfn(False, Edge(2), True, Edge(4), False)
  m.combine(n,lambda x,y: x and y)
  assert m == PWfn(False,Edge(2),True,Edge(2.3),False)
  
  m=PWfn(False, Edge(1), True, Edge(2), False)
  n=PWfn(False, Edge(2), True, Edge(4), False)
  m.combine(n,lambda x,y: x and y)
  assert m == PWfn(False)

def test_PWfn_apply():
  n=PWfn(False, Edge(2), True, Edge(4), False)
  n.apply(lambda x: not x)
  assert n == PWfn(True, Edge(2), False, Edge(4), True)

#TODO: test apply_edges and apply_domains

def test_PWfn_eval():

  p=PWfn(-1,Edge(0),0.1,Edge(2),0.2,Edge(3,Topo.RIGHT),-1)
  assert p.abstract_eval(-2) == -1
  assert p.abstract_eval(0) == -1
  assert p.abstract_eval(1) == 0.1
  assert p.abstract_eval(2) == 0.1
  assert p.abstract_eval(2.5) == 0.2
  assert p.abstract_eval(3) == -1
  assert p.abstract_eval(4.5) == -1

  p=PWfn(-1,Edge(0),0.1,Edge(2),0.2,Edge(3,Topo.RIGHT),-1)
  fn=lambda x: x+1
  assert p.abstract_eval(-2,fn=fn) == 0
  assert p.abstract_eval(0,fn=fn) == 0
  assert p.abstract_eval(1,fn=fn) == 1.1
  assert p.abstract_eval(2,fn=fn) == 1.1
  assert p.abstract_eval(2.5,fn=fn) == 1.2
  assert p.abstract_eval(3,fn=fn) == 0
  assert p.abstract_eval(4.5,fn=fn) == 0


def test_PWlinear_plus():

  x=PWlinear(math.inf,Edge(1,Topo.RIGHT),0,Edge(2,Topo.RIGHT),math.inf)
  y=PWlinear(0,Edge(1,Topo.LEFT),math.inf,Edge(2,Topo.LEFT),0)
  x.plus(y)
  assert x==PWlinear(math.inf,Edge(1,Topo.RIGHT),0,Edge(1,Topo.LEFT),math.inf)

  x=PWlinear(0,Edge(1,Topo.LEFT),1)
  y=PWlinear(0,Edge(1,Topo.RIGHT),4)
  z=PWlinear(1,Edge(1,Topo.LEFT),3)
  # print(f"x {x}\ny {y},\nz {z}")
  z=PWlinear(0,Edge(1,Topo.RIGHT),2,Edge(2,Topo.LEFT),1)
  y.plus(x)
  assert y == PWlinear(0,Edge(1,Topo.RIGHT),4,Edge(1,Topo.LEFT),5)
  y.plus(z)
  assert y==PWlinear(0,Edge(1,Topo.RIGHT),6,Edge(1,Topo.LEFT),7,Edge(2,Topo.LEFT),6)

#TODO: check that simplify does something sensible for intersecting domains

#TODO: check linear fns with slope (not just constant)

#TODO: check that innterpolating up, plus interpolating down, then simplifying yields a constant function, even for small slopes
