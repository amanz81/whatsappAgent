"""
SaaS Database Models.
Defines the Client table for Multi-Tenant Architecture.
"""

from sqlalchemy import Column, Integer, String, Boolean, Text, JSON
from sqlalchemy.orm import Session
from database import Base, SessionLocal, engine
import logging

logger = logging.getLogger(__name__)

class Client(Base):
    """
    Represents a tenant/business using the agent.
    Replaces .env variables for multi-tenancy.
    """
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)                           # Business Name (e.g., "Acme Corp")
    phone_number = Column(String, unique=True, index=True)      # WPP ID (e.g., "1234567890")
    
    wpp_session_id = Column(String, default="default")          # WPPConnect Session
    
    monday_api_key = Column(String)                             # Encrypted API Key
    monday_board_id = Column(String)                            # Monday Board ID
    
    google_drive_folder_id = Column(String)                     # For media storage
    
    gemini_system_prompt = Column(Text)                         # Custom AI Persona/Instructions
    extraction_rules = Column(JSON, default=dict)               # JSON: {"fields": ["price", "date"]}
    
    is_active = Column(Boolean, default=True)

# Create tables
Base.metadata.create_all(bind=engine)

def get_client_config(phone_number: str) -> Client:
    """
    Retrieves the client configuration for a given phone number.
    Returns the Client model instance or None.
    """
    db = SessionLocal()
    try:
        # Normalize phone? assuming exact match for now or strip non-digits
        # clean_phone = ''.join(filter(str.isdigit, phone_number))
        # But WPP IDs often have country code. Store full format.
        
        client = db.query(Client).filter(
            Client.phone_number == phone_number, 
            Client.is_active == True
        ).first()
        
        if not client:
            logger.warning(f"No active client config found for: {phone_number}")
        
        return client
    except Exception as e:
        logger.error(f"Error fetching client config: {e}")
        return None
    finally:
        db.close()
