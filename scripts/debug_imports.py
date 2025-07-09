#!/usr/bin/env python3
# debug_imports.py - Test script to debug model imports

print("Testing model imports...")

try:
    print("1. Importing models module...")
    import sys
    sys.path.append('/home/projects/expense-tracker/backend')
    
    from models import Base, User, Transaction
    print(f"✅ Successfully imported: Base, User, Transaction")
    
    print(f"2. Checking Base.metadata.tables:")
    print(f"   Tables: {list(Base.metadata.tables.keys())}")
    
    if 'users' in Base.metadata.tables and 'transactions' in Base.metadata.tables:
        print("✅ Both 'users' and 'transactions' tables are registered!")
    else:
        print("❌ Tables not properly registered")
        
    print(f"3. User table columns:")
    if 'users' in Base.metadata.tables:
        user_table = Base.metadata.tables['users']
        print(f"   {[col.name for col in user_table.columns]}")
    
    print(f"4. Transaction table columns:")
    if 'transactions' in Base.metadata.tables:
        trans_table = Base.metadata.tables['transactions']
        print(f"   {[col.name for col in trans_table.columns]}")
        
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()