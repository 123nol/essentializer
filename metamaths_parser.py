import re

# 1. A lightweight S-Expression Parser to safely read nested parentheses
def parse_sexp(s):
    s = s.replace('(', ' ( ').replace(')', ' ) ')
    tokens = s.split()
    
    def read_from_tokens(tokens):
        if len(tokens) == 0:
            raise SyntaxError('Unexpected EOF')
        token = tokens.pop(0)
        if token == '(':
            L = []
            while tokens[0] != ')':
                L.append(read_from_tokens(tokens))
            tokens.pop(0) # pop off ')'
            return L
        elif token == ')':
            raise SyntaxError('Unexpected )')
        else:
            return token
            
    return read_from_tokens(tokens)

# Helper to convert parsed python lists back to Lisp strings
def list_to_sexp(lst):
    if isinstance(lst, list):
        return "(" + " ".join(list_to_sexp(x) for x in lst) + ")"
    return str(lst)


# 2. The Main Converter Logic
def convert_metamath_to_pettachainer(metamath_str):
    # Step A: Translate Greek variables to MeTTa variables
    replacements = {
        '𝜑': '$phi',     # phi
        '𝜓': '$psi',     # psi
        '𝜒': '$chi',     # chi
        '𝜃': '$theta',   # theta
        '𝜏': '$tau',     # tau
        '𝜂': '$eta',     # eta (likely the one from your ax-tr rule)
        '𝜆': '$lambda',  # lambda (matches the "cane with a flick" visually)
        '𝜁': '$zeta',    # zeta
        '𝜎': '$sigma',   # sigma
        '𝜇': '$mu',      # mu
        '𝛾': '$gamma',   # gamma
        '𝜌': '$rho'      # rho
    }
    for greek, ascii_var in replacements.items():
        metamath_str = metamath_str.replace(greek, ascii_var)
        
    try:
        parsed = parse_sexp(metamath_str)
    except Exception as e:
        return f";; Error parsing line: {e}"
    
    # Check if it matches the (MkIndexed <num> (...)) structure
    if not (isinstance(parsed, list) and parsed[0] == 'MkIndexed'):
        return ";; Unrecognized structure"
        
    inner = parsed[2]
    kind = inner[0]
    
    # Step B: Extract the name and the mathematical body
    if kind == 'MkAxiom':
        name = inner[1]
        body = inner[2]
    elif kind == 'MkTheorem':
        name = inner[1]
        body = inner[3] # Index 2 is the proof trace, which we skip
    else:
        return f";; Unrecognized kind: {kind}"
        
    # Step C: Process the Body (Meta-level vs Object-level)
    if isinstance(body, list) and body[0] == '->':
        # It's an inference rule with hypotheses.
        # We un-curry chained premises (e.g., -> P1 (-> P2 C)) into a list.
        premises = []
        current = body
        while isinstance(current, list) and current[0] == '->':
            premises.append(current[1])
            current = current[2]
        conclusion = current
        
        # Format premises and conclusion
        premises_sexp = "\n            ".join([f"(Provable {list_to_sexp(p)})" for p in premises])
        conclusion_sexp = f"(Provable {list_to_sexp(conclusion)})"
        
        rule = f"""!(compileadd kb 
   (: (no_inverse {name}) 
      (Implication 
         (Premises 
            {premises_sexp}
         ) 
         (Conclusions 
            {conclusion_sexp}
         )
      ) 
      (STV 1.0 1.0)
   )
)"""
        return rule
        
    else:
        # It's a pure mathematical statement (no meta-level hypotheses)
        body_sexp = list_to_sexp(body)
        rule = f"""!(compileadd kb 
   (: (no_inverse {name}) 
      (Provable {body_sexp}) 
      (STV 1.0 1.0)
   )
)"""
        return rule