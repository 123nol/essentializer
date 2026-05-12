from pantograph.server import Server
from dataclasses import asdict
import json
from enum import Enum

"""
gets rid of this enums that are found in the goals of the ast: eg: <TacticMode.TACTIC: 1>
"""
def json_default(obj):
    if isinstance(obj, Enum):
        return obj.name
    if isinstance(obj, set):
        return list(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

server = Server(imports=["Init"])

state0 = server.goal_start("forall (p q : Prop), Or p q -> Or q p")
state1 = server.goal_tactic(state0, tactic="intro")
out=asdict(state1)
#print(out)
""" 
{'state_id': 1, 'goals': [{'id': '_uniq.11', 'variables': [{'t': 'Prop', 'v': None, 'name': 'p✝'}], 'target': '∀ (q : Prop), p✝ ∨ q → q ∨ p✝', 'sibling_dep': None, 'name': None, 'mode': <TacticMode.TACTIC: 1>}], 'messages': [], '_sentinel': []}

"""
print(json.dumps(out, indent=2, ensure_ascii=False, default=json_default))


"""
{
  "state_id": 1,
  "goals": [
    {
      "id": "_uniq.11",
      "variables": [
        {
          "t": "Prop",
          "v": null,
          "name": "p✝"
        }
      ],
      "target": "∀ (q : Prop), p✝ ∨ q → q ∨ p✝",
      "sibling_dep": null,
      "name": null,
      "mode": "TACTIC"
    }
  ],
  "messages": [],
  "_sentinel": []
}

"""