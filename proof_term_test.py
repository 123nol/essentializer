from pantograph.server import Server
import json

server = Server(imports=["Init"])

code = """
theorem my_id (P Q: Prop): (P → (P → Q) → Q) := by
  intro hp

 


"""

units = server.check_compile(code, new_constants=True)

server.load_definitions(code)

info = server.env_inspect("my_id", print_value=True)
value=info["value"]



if value is None:
    print("No value found. Did you pass print_value=True?")
elif isinstance(value, dict) and "pp" in value:
    print(value["pp"])
else:
    print(value)

#print(json.dumps(info, indent=2, ensure_ascii=False))