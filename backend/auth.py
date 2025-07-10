# backend/auth.py
# Enhanced authentication with JWT tokens and security features

from datetime import datetime, timedelta
from typing import Optional, Union
from passlib.context import CryptContext
from jose import JWTError, jwt
from fastapi import HTTPException, status
import secrets
import hashlib

# Configuration
SECRET_KEY = "your-secret-key-change-in-production"  # Should be from environment variable
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class AuthManager:
    """Enhanced authentication manager with JWT tokens and security features."""
    
    def __init__(self, secret_key: str = SECRET_KEY):
        self.secret_key = secret_key
        self.algorithm = ALGORITHM
        self.access_token_expire_minutes = ACCESS_TOKEN_EXPIRE_MINUTES
        self.refresh_token_expire_days = REFRESH_TOKEN_EXPIRE_DAYS
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a plaintext password against its hash."""
        return pwd_context.verify(plain_password, hashed_password)
    
    def get_password_hash(self, password: str) -> str:
        """Hash a password for storing."""
        return pwd_context.hash(password)
    
    def validate_password_strength(self, password: str) -> dict:
        """Validate password strength and return feedback."""
        issues = []
        score = 0
        
        # Length check
        if len(password) < 8:
            issues.append("Password must be at least 8 characters long")
        else:
            score += 1
        
        # Character variety checks
        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        has_special = any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password)
        
        if not has_upper:
            issues.append("Password should contain uppercase letters")
        else:
            score += 1
            
        if not has_lower:
            issues.append("Password should contain lowercase letters")
        else:
            score += 1
            
        if not has_digit:
            issues.append("Password should contain numbers")
        else:
            score += 1
            
        if not has_special:
            issues.append("Password should contain special characters")
        else:
            score += 1
        
        # Common password check (basic)
        common_passwords = ["password", "123456", "qwerty", "admin", "letmein"]
        if password.lower() in common_passwords:
            issues.append("Password is too common")
            score = max(0, score - 2)
        
        # Strength levels
        if score >= 4:
            strength = "strong"
        elif score >= 3:
            strength = "medium"
        elif score >= 2:
            strength = "weak"
        else:
            strength = "very_weak"
        
        return {
            "valid": len(issues) == 0,
            "strength": strength,
            "score": score,
            "issues": issues
        }
    
    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """Create a JWT access token."""
        to_encode = data.copy()
        
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=self.access_token_expire_minutes)
        
        to_encode.update({
            "exp": expire,
            "type": "access",
            "iat": datetime.utcnow()
        })
        
        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt
    
    def create_refresh_token(self, data: dict) -> str:
        """Create a JWT refresh token."""
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(days=self.refresh_token_expire_days)
        
        to_encode.update({
            "exp": expire,
            "type": "refresh",
            "iat": datetime.utcnow()
        })
        
        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt
    
    def verify_token(self, token: str, token_type: str = "access") -> dict:
        """Verify and decode a JWT token."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            
            # Check token type
            if payload.get("type") != token_type:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid token type. Expected {token_type}"
                )
            
            # Check expiration
            exp = payload.get("exp")
            if exp is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token missing expiration"
                )
            
            if datetime.utcnow().timestamp() > exp:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has expired"
                )
            
            return payload
            
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials"
            )
    
    def refresh_access_token(self, refresh_token: str) -> dict:
        """Create a new access token from a valid refresh token."""
        payload = self.verify_token(refresh_token, "refresh")
        
        # Extract user data (remove token-specific fields)
        user_data = {k: v for k, v in payload.items() if k not in ["exp", "iat", "type"]}
        
        # Create new access token
        access_token = self.create_access_token(user_data)
        
        return {
            "access_token": access_token,
            "token_type": "bearer"
        }
    
    def generate_reset_token(self, user_email: str) -> str:
        """Generate a password reset token."""
        # Create a secure random token
        reset_token = secrets.token_urlsafe(32)
        
        # In production, store this token in database with expiration
        # For now, we'll create a JWT with the reset token
        data = {
            "email": user_email,
            "reset_token": reset_token,
            "type": "password_reset"
        }
        
        expire = datetime.utcnow() + timedelta(hours=1)  # 1 hour expiry
        data["exp"] = expire
        
        encoded_token = jwt.encode(data, self.secret_key, algorithm=self.algorithm)
        return encoded_token
    
    def verify_reset_token(self, token: str) -> dict:
        """Verify a password reset token."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            
            if payload.get("type") != "password_reset":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid reset token"
                )
            
            return payload
            
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset token"
            )
    
    def hash_file_content(self, content: bytes) -> str:
        """Create a hash of file content for duplicate detection."""
        return hashlib.sha256(content).hexdigest()
    
    def generate_session_id(self) -> str:
        """Generate a secure session ID."""
        return secrets.token_urlsafe(32)

# Global auth manager instance
auth_manager = AuthManager()

# Convenience functions for backward compatibility
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return auth_manager.verify_password(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Hash a password."""
    return auth_manager.get_password_hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create an access token."""
    return auth_manager.create_access_token(data, expires_delta)

def verify_token(token: str) -> dict:
    """Verify an access token."""
    return auth_manager.verify_token(token, "access")

class RateLimiter:
    """Simple rate limiter for authentication attempts."""
    
    def __init__(self):
        self.attempts = {}  # In production, use Redis or database
        self.max_attempts = 5
        self.lockout_time = timedelta(minutes=15)
    
    def is_rate_limited(self, identifier: str) -> bool:
        """Check if an identifier (IP or email) is rate limited."""
        if identifier not in self.attempts:
            return False
        
        attempts_data = self.attempts[identifier]
        
        # Check if lockout period has expired
        if datetime.utcnow() > attempts_data["lockout_until"]:
            del self.attempts[identifier]
            return False
        
        return attempts_data["count"] >= self.max_attempts
    
    def record_attempt(self, identifier: str, success: bool = False):
        """Record an authentication attempt."""
        now = datetime.utcnow()
        
        if identifier not in self.attempts:
            self.attempts[identifier] = {
                "count": 0,
                "lockout_until": now
            }
        
        if success:
            # Reset on successful login
            del self.attempts[identifier]
        else:
            # Increment failed attempts
            self.attempts[identifier]["count"] += 1
            if self.attempts[identifier]["count"] >= self.max_attempts:
                self.attempts[identifier]["lockout_until"] = now + self.lockout_time
    
    def get_remaining_attempts(self, identifier: str) -> int:
        """Get remaining attempts before lockout."""
        if identifier not in self.attempts:
            return self.max_attempts
        
        return max(0, self.max_attempts - self.attempts[identifier]["count"])

# Global rate limiter
rate_limiter = RateLimiter()

class SecurityManager:
    """Additional security utilities."""
    
    @staticmethod
    def validate_email(email: str) -> bool:
        """Basic email validation."""
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize uploaded filename."""
        import re
        # Remove path separators and dangerous characters
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # Limit length
        if len(filename) > 255:
            filename = filename[:255]
        return filename
    
    @staticmethod
    def check_file_type(filename: str, allowed_extensions: set) -> bool:
        """Check if file type is allowed."""
        if not filename:
            return False
        
        extension = '.' + filename.split('.')[-1].lower()
        return extension in allowed_extensions
    
    @staticmethod
    def generate_csrf_token() -> str:
        """Generate CSRF token."""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def validate_csrf_token(token: str, stored_token: str) -> bool:
        """Validate CSRF token."""
        return secrets.compare_digest(token, stored_token)

# Global security manager
security_manager = SecurityManager()

# JWT Token dependency for FastAPI
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def get_current_user_from_token(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """Extract user information from JWT token."""
    try:
        payload = auth_manager.verify_token(credentials.credentials)
        user_email = payload.get("sub")
        
        if user_email is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials"
            )
        
        return payload
        
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

class TokenBlacklist:
    """Token blacklist for logout functionality."""
    
    def __init__(self):
        self.blacklisted_tokens = set()  # In production, use Redis
    
    def add_token(self, token: str):
        """Add token to blacklist."""
        self.blacklisted_tokens.add(token)
    
    def is_blacklisted(self, token: str) -> bool:
        """Check if token is blacklisted."""
        return token in self.blacklisted_tokens
    
    def cleanup_expired_tokens(self):
        """Remove expired tokens from blacklist."""
        # In production, this would check token expiration
        # For now, we'll just clear old tokens periodically
        pass

# Global token blacklist
token_blacklist = TokenBlacklist()

def validate_auth_token(token: str) -> dict:
    """Validate token and check blacklist."""
    if token_blacklist.is_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked"
        )
    
    return auth_manager.verify_token(token)

# Enhanced authentication utilities
class AuthUtils:
    """Additional authentication utilities."""
    
    @staticmethod
    def generate_user_avatar_url(email: str) -> str:
        """Generate Gravatar URL for user email."""
        import hashlib
        email_hash = hashlib.md5(email.lower().encode()).hexdigest()
        return f"https://www.gravatar.com/avatar/{email_hash}?d=identicon&s=200"
    
    @staticmethod
    def log_security_event(event_type: str, user_email: str, details: dict = None):
        """Log security events for monitoring."""
        # In production, this would log to a security monitoring system
        print(f"SECURITY EVENT: {event_type} for {user_email} - {details}")
    
    @staticmethod
    def check_password_breached(password: str) -> bool:
        """Check if password appears in known breaches (placeholder)."""
        # In production, this could integrate with HaveIBeenPwned API
        # For now, just check against a few common passwords
        common_breached = [
            "password", "123456", "password123", "admin", "qwerty",
            "letmein", "welcome", "monkey", "1234567890"
        ]
        return password.lower() in common_breached

# Global auth utils
auth_utils = AuthUtils()