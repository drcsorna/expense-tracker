# reset_database.py
# Clean reset of database with new 3.0 schema

import os
import sqlite3
from pathlib import Path

def reset_database():
    """Reset database with clean 3.0 schema."""
    
    # Database file path
    db_file = Path("database.db")
    
    print("🗑️  Resetting Expense Tracker Database...")
    
    # Step 1: Backup old database (optional)
    if db_file.exists():
        backup_file = f"database_backup_{int(__import__('time').time())}.db"
        print(f"📦 Creating backup: {backup_file}")
        import shutil
        shutil.copy(db_file, backup_file)
        
        # Remove old database
        os.remove(db_file)
        print("✅ Old database removed")
    
    # Step 2: Create new database with 3.0 schema
    print("🔨 Creating new database schema...")
    
    from backend.models import create_tables, Base, engine
    
    # Create all new tables
    Base.metadata.create_all(bind=engine)
    print("✅ New database schema created")
    
    # Step 3: Create a test user (optional)
    create_test_user = input("Create test user? (y/n): ").lower() == 'y'
    
    if create_test_user:
        from backend.models import SessionLocal, User
        from backend.auth import get_password_hash
        
        db = SessionLocal()
        try:
            # Create test user
            test_user = User(
                email="test@example.com",
                hashed_password=get_password_hash("password123"),
                preferences={
                    "duplicate_detection": {
                        "amount_tolerance": 0.01,
                        "date_range_days": 3,
                        "beneficiary_similarity_threshold": 0.8
                    },
                    "categorization": {
                        "auto_approve_high_confidence": False,
                        "confidence_threshold": 0.9
                    },
                    "ui": {
                        "theme": "auto",
                        "default_currency": "EUR"
                    }
                }
            )
            
            db.add(test_user)
            db.commit()
            db.refresh(test_user)
            
            # Create default categories for test user
            from backend.models import create_default_categories
            import asyncio
            asyncio.run(create_default_categories(db, test_user.id))
            
            print(f"✅ Test user created: test@example.com / password123")
            
        except Exception as e:
            print(f"❌ Error creating test user: {e}")
        finally:
            db.close()
    
    print("\n🎉 Database reset complete!")
    print("🚀 Restart your server: python start_server.py")
    print("\n📊 New Features Available:")
    print("   • ML-powered categorization")
    print("   • Smart duplicate detection")
    print("   • Real-time progress tracking")
    print("   • Advanced analytics")
    print("   • User-defined categories")

def show_database_info():
    """Show current database information."""
    
    db_file = Path("database.db")
    
    if not db_file.exists():
        print("❌ No database file found")
        return
    
    print("📊 Current Database Info:")
    print(f"   File: {db_file}")
    print(f"   Size: {db_file.stat().st_size / 1024:.1f} KB")
    
    # Check tables
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    
    print(f"   Tables: {len(tables)}")
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table[0]}")
        count = cursor.fetchone()[0]
        print(f"     - {table[0]}: {count} rows")
    
    conn.close()

if __name__ == "__main__":
    print("🔧 Expense Tracker Database Manager")
    print("1. Show current database info")
    print("2. Reset database (clean slate)")
    print("3. Exit")
    
    choice = input("\nChoose option (1-3): ").strip()
    
    if choice == "1":
        show_database_info()
    elif choice == "2":
        print("\n⚠️  WARNING: This will DELETE all existing data!")
        confirm = input("Are you sure? Type 'yes' to confirm: ").lower()
        if confirm == "yes":
            reset_database()
        else:
            print("❌ Reset cancelled")
    elif choice == "3":
        print("👋 Goodbye!")
    else:
        print("❌ Invalid choice")