#!/usr/bin/env python3
"""
Development tools for Expense Tracker 2.0
Database management, sample data creation, etc.
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime, date
from decimal import Decimal

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from backend.models import engine, Base, SessionLocal, User, Transaction, Category, create_default_categories
from backend.auth import get_password_hash

def reset_database():
    """Reset the database by dropping and recreating all tables."""
    print("⚠️  Resetting database...")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    print("✅ Database reset complete!")

def create_sample_user():
    """Create a sample user for testing."""
    db = SessionLocal()
    try:
        # Check if user already exists
        existing_user = db.query(User).filter(User.email == "demo@example.com").first()
        if existing_user:
            print("👤 Demo user already exists")
            return existing_user
        
        # Create demo user
        user = User(
            email="demo@example.com",
            hashed_password=get_password_hash("demo123"),
            created_at=datetime.utcnow()
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        
        # Create default categories
        create_default_categories(user.id, db)
        
        print("👤 Created demo user: demo@example.com / demo123")
        return user
        
    except Exception as e:
        print(f"❌ Error creating sample user: {e}")
        db.rollback()
        return None
    finally:
        db.close()

def create_sample_transactions(user_id: int, count: int = 50):
    """Create sample transactions for testing."""
    db = SessionLocal()
    try:
        # Sample transaction data
        sample_transactions = [
            {"beneficiary": "Grocery Store", "amount": Decimal("-45.67"), "category": "Food & Dining"},
            {"beneficiary": "Gas Station", "amount": Decimal("-52.30"), "category": "Transportation"},
            {"beneficiary": "Coffee Shop", "amount": Decimal("-4.50"), "category": "Food & Dining"},
            {"beneficiary": "Online Store", "amount": Decimal("-89.99"), "category": "Shopping"},
            {"beneficiary": "Salary Deposit", "amount": Decimal("2500.00"), "category": "Income"},
            {"beneficiary": "Electric Bill", "amount": Decimal("-125.45"), "category": "Bills & Utilities"},
            {"beneficiary": "Internet Bill", "amount": Decimal("-49.99"), "category": "Bills & Utilities"},
            {"beneficiary": "Restaurant", "amount": Decimal("-67.80"), "category": "Food & Dining"},
            {"beneficiary": "Movie Theater", "amount": Decimal("-25.50"), "category": "Entertainment"},
            {"beneficiary": "Pharmacy", "amount": Decimal("-18.75"), "category": "Healthcare"},
        ]
        
        import random
        from datetime import timedelta
        
        created_count = 0
        for i in range(count):
            # Pick random sample transaction
            sample = random.choice(sample_transactions)
            
            # Random date within last 90 days
            random_days = random.randint(0, 90)
            transaction_date = date.today() - timedelta(days=random_days)
            
            # Create transaction
            transaction = Transaction(
                transaction_date=transaction_date,
                beneficiary=f"{sample['beneficiary']} {i+1}",
                amount=sample['amount'] + Decimal(random.uniform(-10, 10)),
                category=sample['category'],
                labels=[],
                is_private=random.choice([True, False]),
                owner_id=user_id,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            db.add(transaction)
            created_count += 1
            
            # Commit in batches
            if i % 10 == 0:
                db.commit()
        
        db.commit()
        print(f"💰 Created {created_count} sample transactions")
        
    except Exception as e:
        print(f"❌ Error creating sample transactions: {e}")
        db.rollback()
    finally:
        db.close()

def show_stats():
    """Show database statistics."""
    db = SessionLocal()
    try:
        user_count = db.query(User).count()
        transaction_count = db.query(Transaction).count()
        category_count = db.query(Category).count()
        
        print("📊 Database Statistics:")
        print(f"   Users: {user_count}")
        print(f"   Transactions: {transaction_count}")
        print(f"   Categories: {category_count}")
        
    finally:
        db.close()

def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(description="Expense Tracker 2.0 Development Tools")
    parser.add_argument("command", choices=["reset", "demo", "stats"], 
                       help="Command to execute")
    parser.add_argument("--transactions", type=int, default=50,
                       help="Number of sample transactions to create")
    
    args = parser.parse_args()
    
    if args.command == "reset":
        reset_database()
        
    elif args.command == "demo":
        reset_database()
        user = create_sample_user()
        if user:
            create_sample_transactions(user.id, args.transactions)
        show_stats()
        print("\n🎉 Demo setup complete!")
        print("   Login with: demo@example.com / demo123")
        
    elif args.command == "stats":
        show_stats()

if __name__ == "__main__":
    main()