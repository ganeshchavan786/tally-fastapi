import yaml
import re

def compare_yaml_sql(yaml_file, sql_file, label):
    """Compare YAML config fields with SQL columns"""
    print(f'\n{"=" * 70}')
    print(f'{label}: {yaml_file} vs {sql_file}')
    print('=' * 70)
    
    try:
        # Load YAML config
        with open(yaml_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # Load SQL file
        with open(sql_file, 'r', encoding='utf-8') as f:
            sql_content = f.read()
    except FileNotFoundError as e:
        print(f'  File not found: {e}')
        return

    # Parse SQL tables and columns
    sql_tables = {}
    current_table = None
    for line in sql_content.split('\n'):
        line = line.strip()
        if line.startswith('create table '):
            current_table = line.replace('create table ', '').strip()
            sql_tables[current_table] = []
        elif current_table and line and not line.startswith(')') and not line.startswith('('):
            col_match = re.match(r'^(\w+)\s+', line)
            if col_match:
                sql_tables[current_table].append(col_match.group(1))

    # Compare YAML fields with SQL columns
    all_tables = config.get('master', []) + config.get('transaction', [])
    mismatches = []

    for table in all_tables:
        table_name = table.get('name', '')
        yaml_fields = [f.get('name', '') for f in table.get('fields', [])]
        sql_columns = sql_tables.get(table_name, [])
        
        missing_in_sql = [f for f in yaml_fields if f not in sql_columns]
        missing_in_yaml = [c for c in sql_columns if c not in yaml_fields and c != 'guid']
        
        if missing_in_sql or missing_in_yaml:
            mismatches.append({
                'table': table_name,
                'missing_in_sql': missing_in_sql,
                'missing_in_yaml': missing_in_yaml
            })

    if mismatches:
        print(f'\n  Found {len(mismatches)} tables with mismatches:\n')
        for m in mismatches:
            print(f"  Table: {m['table']}")
            if m['missing_in_sql']:
                print(f"    In YAML but NOT in SQL: {m['missing_in_sql']}")
            if m['missing_in_yaml']:
                print(f"    In SQL but NOT in YAML: {m['missing_in_yaml']}")
            print()
    else:
        print('\n  All tables match!')

# Compare both configs
compare_yaml_sql('tally-export-config.yaml', 'database-structure.sql', 'FULL SYNC')
compare_yaml_sql('tally-export-config-incremental.yaml', 'database-structure-incremental.sql', 'INCREMENTAL SYNC')
