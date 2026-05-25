import os
import json
from bs4 import BeautifulSoup

def parse_epik_mathlib_html(directory_path):
    graph_data = []

    print(f"Scanning directory: {directory_path}...")

    for root, dirs, files in os.walk(directory_path):
        for file in files:
            if file.endswith(".html"):
                filepath = os.path.join(root, file)
                
                with open(filepath, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f, 'html.parser')
                    declarations = soup.find_all('div', class_='decl')
                    
                    for decl in declarations:
                        # 1. Base Entity Info
                        name_tag = decl.find('h4', class_='decl-name')
                        name = name_tag.text.strip() if name_tag else "Unknown"
                        
                        type_tag = decl.find('span', class_='decl-kind')
                        decl_type = type_tag.text.strip() if type_tag else "declaration"
                        
                        attributes = [attr.text.strip().strip('@[]') for attr in decl.find_all('span', class_='decl-attr')]

                        # 3. Extract Dependencies, Extends, and Instances
                        signature_block = decl.find('div', class_='decl-sig')
                        depends_on = []
                        extends = []
                        is_instance_of = [] # NEW: For the Induction rule!
                        
                        if signature_block:
                            sig_text = signature_block.text
                            links = signature_block.find_all('a')
                            
                            for a_tag in links:
                                href = a_tag.get('href')
                                if href and not href.startswith('http'):
                                    target = a_tag.text.strip()
                                    
                                    # Rule A: Extracting 'extends' (for Abduction)
                                    if 'extends' in sig_text and sig_text.find('extends') < sig_text.find(target):
                                        extends.append(target)
                                        
                                    # Rule B: Extracting 'instances' (for Induction)
                                    # If this block is declaring an instance, the links inside its signature 
                                    # represent the Type Class being satisfied and the Object satisfying it.
                                    elif decl_type == 'instance':
                                        is_instance_of.append(target)
                                        
                                    # Rule C: Standard dependency
                                    else:
                                        depends_on.append(target)
                                        
                        fields = []
                        if decl_type in ['structure', 'class']:
                            field_list = decl.find('ul', class_='structure-fields')
                            if field_list:
                                for li in field_list.find_all('li'):
                                    field_name_tag = li.find('span', class_='decl-name')
                                    if field_name_tag:
                                        fields.append(field_name_tag.text.strip())

                        # Build the JSON Object
                        entity_data = {
                            "name": name,
                            "type": decl_type,
                            "attributes": list(set(attributes)),
                            "extends": list(set(extends)),
                            "is_instance_of": list(set(is_instance_of)), # Added here
                            "fields": list(set(fields)),
                            "depends_on": list(set(depends_on))
                        }
                        graph_data.append(entity_data)
                        
    output_file = 'epik_mathlib_graph.json'
    with open(output_file, 'w', encoding='utf-8') as out_file:
        json.dump(graph_data, out_file, indent=4)
        
    print(f"Successfully parsed {len(graph_data)} entities into {output_file}.")

if __name__ == "__main__":
    target_directory = "./.lake/build/doc/"
    if os.path.exists(target_directory):
        parse_epik_mathlib_html(target_directory)
    else:
        print(f"Error: Directory '{target_directory}' not found.")