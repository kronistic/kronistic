import re
from lark import Lark, UnexpectedInput, Visitor

# KRON_DIR_RE = re.compile(r'^\s*@kron(istic)?(\s+if\s+needed)?\s*$', re.IGNORECASE)

# KRON_DIR_RE = re.compile(r'^\s*@kron(istic)?(\s+if(\s+really)*\s+needed)?\s*$', re.IGNORECASE)

# "synonyms" for needed: all-important, critical, essential, imperative, indispensable, must-have, necessary, necessitous, needful, required, requisite, vital
# "synonyms" for available: employable, exploitable, practicable, serviceable, usable (also useable), free, open, yes
# "synonyms" for "really": achingly, almighty, archly, awful, awfully, badly, beastly, blisteringly, bone, colossally, corking, cracking, damn, damned, dang, deadly, desperately, eminently, enormously, especially, ever, exceedingly (also exceeding), extra, extremely, fabulously, fantastically, far, fiercely, filthy, frightfully, full, greatly, heavily, highly, hugely, immensely, incredibly, intensely, jolly, majorly, mightily, mighty, monstrous [chiefly dialect], mortally, most, much, particularly, passing, rattling, real, right, roaring, roaringly, seriously, severely, so, sore, sorely, spanking, specially, stinking, such, super, supremely, surpassingly, terribly, that, thumping, too, unco, uncommonly, vastly, very, vitally, way, whacking, wicked, wildly, absolutely, altogether, completely, downright, entirely, flat-out, fully, positively, purely, radically, thoroughly, totally, utterly, wholly

#TODO: add in synonyms for "really"
KRON_DIR_CFG = r"""
  start: _w{_KRON} _list{spec}?

  spec: _w{_AVAILABLE}? (forpeople? ifneeded?|ifneeded? forpeople?) 

  ifneeded: _w{"if"} _w{REALLY}* _w{NEEDED}	

  forpeople: (_w{"for"}|_w{"to"}) _list{PERSON}

  PERSON: /\s[^,\s]+/

  _KRON: "@kron"|"@kronistic"

  _AVAILABLE: "available"|"employable"|"exploitable"|"practicable"|"serviceable"|"usable"|"useable"|"free"|"open"|"yes"

  NEEDED: "needed"|"all-important"|"critical"|"essential"|"imperative"|"indispensable"|"must-have"|"necessary"|"necessitous"|"needful"|"required"|"requisite"|"vital"

  REALLY: "really"|"achingly"|"almighty"|"awful"|"awfully"|"badly"|"colossally"|"damn"|"damned"|"dang"|"deadly"|"desperately"|"eminently"|"enormously"|"especially"|"exceedingly"|"exceeding"|"extra"|"extremely"|"fabulously"|"fantastically"|"far"|"fiercely"|"filthy"|"frightfully"|"greatly"|"heavily"|"highly"|"hugely"|"immensely"|"incredibly"|"intensely"|"mightily"|"mighty"|"most"|"much"|"particularly"|"real"|"seriously"|"severely"|"so"|"sore"|"sorely"|"stinking"|"super"|"supremely"|"surpassingly"|"very"|"vitally"|"way"|"wildly"|"absolutely"|"altogether"|"completely"|"entirely"|"positively"|"thoroughly"|"totally"|"utterly"|"wholly"|"rly"

  _list{word}: word _w{","}? | _list{word} (_w{","}|_w{"and"})+ word

  _w{word}: _WS* word _WS*

  _WS: /\s/        

  %ignore "." 
"""

class BuildCostDict(Visitor):

  def start(self,tree):
    #each spec can list some people (we should default to everyone) with some ifneeded cost (default should be 0), we merge into a dict. if a person shows up twice we use min of the costs. (note that's not what'll happen from separate (overlapping) kronduty events, which implicitly add.)
    # print(f"start node, tree {tree}")
    if tree.children==[]:
      tree.data={'everyone':0}
    else:
      tree.data = {}
      for c in tree.children:
        for k,v in c.data.items():
          tree.data[k] = min(v,tree.data[k]) if k in tree.data.keys() else v

  def spec(self,tree):
    #build a dict of the people in this spec ("everyone" if none) and their ifneeded cost (0 if none)
    #ugh there must be a better way to pull out these vals:
    cost = next((c.data['cost'] for c in tree.children if 'cost' in c.data.keys()), 0)
    people = next((c.data['people'] for c in tree.children if 'people' in c.data.keys()),["everyone"])
    tree.data={k:cost for k in people}
  
  def forpeople(self,tree):
    tree.data = {'people':[p.value.replace('"','').strip().rstrip('.').lower() for p in tree.children]}

  def ifneeded(self,tree):
    #TODO: different cost for different word? eg "if vastly vital">>"if really needed"?
    tree.data = {'cost':len(tree.children)}

grammar = Lark(KRON_DIR_CFG,g_regex_flags=re.I)

def parse_kron_directive(s):
    # Returns a pair `(kron_duty, priority)`.
    # `kron_duty`: flag indicating whether this is a kron duty event
    # `priority`: optional int. None => required, int => optional with int giving priority

  is_kron_directive=re.search(r'@kron',s,flags=re.I)
  if is_kron_directive is not None:

    try:
      tree = grammar.parse(s,start='start') 
    except UnexpectedInput as ex:
      #TODO do something less laconic when parsing fails?
      print(f"kron tag found but parsing kron directive failed")
      return True, {}
    
    # we'll be returning a lookup from "person" strings to cost
    # (these persons will be resolved to emails, via groups, in mask_utils)
    BuildCostDict().visit(tree)
    costs = tree.data
    # Use of person or group specific costs is made to look like a parse error:
    return True, costs if tuple(costs.keys()) == ('everyone',) else {}
  #this is the case where there is no " @kron" in the string:
  return False, None
