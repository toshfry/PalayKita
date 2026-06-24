from sqlalchemy import (Column, Integer, String, Numeric, Boolean,
                        DateTime, Date, Text, ForeignKey)
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime, date as _date

Base = declarative_base()


class User(Base):
    __tablename__ = 'users'
    id           = Column(Integer, primary_key=True)
    username     = Column(String(50), unique=True, nullable=False)
    password_hash= Column(String(255), nullable=False)
    role         = Column(String(20), default='staff')   # admin | staff
    is_active    = Column(Boolean, default=True)
    created_at   = Column(DateTime, default=datetime.utcnow)


class Settings(Base):
    __tablename__ = 'settings'
    id                        = Column(Integer, primary_key=True)
    business_name             = Column(String(100), default='PalayKita Rice Mill')
    milling_rate_per_kg       = Column(Numeric(10, 2), default=1.00)
    chaff_rate_per_kg         = Column(Numeric(10, 2), default=0.50)
    currency_symbol           = Column(String(5),  default='₱')
    receipt_footer            = Column(Text,        default='Thank you for your business! God bless.')
    auto_generate_daily_report= Column(Boolean, default=False)
    daily_report_time         = Column(String(10),  default='18:00')
    server_port               = Column(Integer, default=5000)
    updated_at                = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MillingTransaction(Base):
    __tablename__ = 'milling_transactions'
    id                 = Column(Integer, primary_key=True)
    transaction_number = Column(String(30), unique=True, nullable=False)
    customer_name      = Column(String(100), nullable=True)
    contact_number     = Column(String(30),  nullable=True)
    kilos_milled       = Column(Numeric(10, 2), nullable=False)
    milling_rate_per_kg= Column(Numeric(10, 2), nullable=False)
    gross_fee          = Column(Numeric(10, 2), nullable=False)
    has_chaff_deduction= Column(Boolean, default=False)
    chaff_kilos        = Column(Numeric(10, 2), default=0)
    chaff_rate_per_kg  = Column(Numeric(10, 2), default=0)
    chaff_deduction    = Column(Numeric(10, 2), default=0)
    net_amount         = Column(Numeric(10, 2), nullable=False)
    amount_paid        = Column(Numeric(10, 2), default=0)
    balance            = Column(Numeric(10, 2), default=0)
    payment_status     = Column(String(20), default='Unpaid')  # Paid | Unpaid | Partial
    payment_method     = Column(String(30), nullable=True)
    notes              = Column(Text, nullable=True)
    transaction_date   = Column(Date, default=_date.today)
    created_at         = Column(DateTime, default=datetime.utcnow)
    updated_at         = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by         = Column(String(50), nullable=True)

    payments = relationship('Payment', back_populates='transaction',
                            cascade='all, delete-orphan')


class Payment(Base):
    __tablename__ = 'payments'
    id             = Column(Integer, primary_key=True)
    transaction_id = Column(Integer, ForeignKey('milling_transactions.id'), nullable=False)
    amount         = Column(Numeric(10, 2), nullable=False)
    payment_method = Column(String(30), nullable=True)
    payment_date   = Column(DateTime, default=datetime.utcnow)
    notes          = Column(Text, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow)
    created_by     = Column(String(50), nullable=True)

    transaction = relationship('MillingTransaction', back_populates='payments')


class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, nullable=True)
    action     = Column(String(100), nullable=False)
    details    = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
