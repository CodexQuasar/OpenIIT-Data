# Background task durability and audit records for visit prediction refresh
# and place cluster updates. Tracks task lifecycle, retry attempts,
# success/failure metrics, and provides audit trails per RBI/DPDP requirements.

from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Union
from dataclasses import dataclass, field
from enum import Enum
import uuid
import logging

from sqlalchemy.orm import Session
from sqlalchemy import Column, String, DateTime, Integer, Boolean, Text, Enum as SQLEnum, Index, JSON

from data.models import Base


class TaskStatus(str, Enum):
    """Lifecycle status of a background task."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"
    CANCELLED = "cancelled"


class TaskType(str, Enum):
    """Types of background tasks."""
    REFRESH_ACCOUNT_PREDICTION = "refresh_account_prediction"
    UPDATE_PLACE_CLUSTERS = "update_place_clusters"
    SYNC_OFFLINE_VISITS = "sync_offline_visits"
    CLEANUP_RETENTION = "cleanup_retention"
    REEVALUATE_CALIBRATION = "reevaluate_calibration"


@dataclass
class TaskRecord:
    """Immutable record of a background task execution."""
    task_id: str
    task_type: TaskType
    account_id: Optional[str] = None
    triggered_by: Optional[str] = None  # user_id, system, scheduler
    status: TaskStatus = TaskStatus.QUEUED
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    result_data: Optional[Dict[str, Any]] = None  # e.g., new prediction, cluster update
    execution_time_ms: Optional[int] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class TaskModel(Base):
    """SQLAlchemy model for background task persistence."""
    __tablename__ = "background_tasks"

    id = Column(String, primary_key=True)
    task_type = Column(String, nullable=False, index=True)
    account_id = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default="queued")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    result_data = Column(JSON, nullable=True)
    execution_time_ms = Column(Integer, nullable=True)
    triggered_by = Column(String, nullable=True, index=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_tasks_type_status", "task_type", "status"),
        Index("ix_tasks_account_status", "account_id", "status"),
        Index("ix_tasks_created_at", "created_at"),
    )


class TaskLogger:
    """Logs background task execution to the audit trail."""
    def __init__(self):
        self.db = SessionLocal()

    def record_task(self, record: TaskRecord) -> TaskModel:
        """Persist a task record."""
        model = TaskModel(
            id=record.task_id,
            task_type=record.task_type.value,
            account_id=record.account_id,
            status=record.status.value,
            started_at=record.started_at,
            completed_at=record.completed_at,
            error_message=record.error_message,
            retry_count=record.retry_count,
            max_retries=record.max_retries,
            result_data=record.result_data,
            execution_time_ms=record.execution_time_ms,
            triggered_by=record.triggered_by,
            ip_address=record.ip_address,
            user_agent=record.user_agent,
        )
        self.db.add(model)
        self.db.commit()
        self.db.refresh(model)
        return model

    def log_task_started(
        self,
        task_type: TaskType,
        account_id: Optional[str] = None,
        triggered_by: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> str:
        """Record task start and return task_id."""
        task_id = f"task_{uuid.uuid4().hex[:14]}"
        record = TaskRecord(
            task_id=task_id,
            task_type=task_type,
            account_id=account_id,
            triggered_by=triggered_by,
            status=TaskStatus.RUNNING,
            started_at=datetime.utcnow(),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.record_task(record)
        return task_id

    def log_task_completed(
        self,
        task_id: str,
        result_data: Dict[str, Any],
        execution_time_ms: int,
        status: TaskStatus = TaskStatus.COMPLETED,
    ) -> None:
        """Record task completion."""
        model = self.db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if model:
            model.status = status.value
            model.completed_at = datetime.utcnow()
            model.result_data = result_data
            model.execution_time_ms = execution_time_ms
            self.db.commit()

    def log_task_failed(
        self,
        task_id: str,
        error_message: str,
        execution_time_ms: Optional[int] = None,
    ) -> None:
        """Record task failure and handle retry logic."""
        model = self.db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if model:
            model.status = TaskStatus.FAILED.value
            model.completed_at = datetime.utcnow()
            model.error_message = error_message
            model.execution_time_ms = execution_time_ms
            # Auto-retry if under max
            if model.retry_count < model.max_retries:
                model.retry_count += 1
                model.status = TaskStatus.RETRY.value
            self.db.commit()


class TaskManager:
    """Manages background task lifecycle with retry and audit."""

    def __init__(self, db: Session, audit_logger: TaskLogger):
        self.db = db
        self.audit_logger = audit_logger

    def submit_task(
        self,
        task_type: TaskType,
        account_id: Optional[str] = None,
        triggered_by: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> str:
        """Submit a new background task. Returns task_id."""
        task_id = self.audit_logger.log_task_started(
            task_type=task_type,
            account_id=account_id,
            triggered_by=triggered_by,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return task_id

    def get_task_status(self, task_id: str) -> Optional[TaskRecord]:
        """Get current status of a task."""
        model = self.db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if not model:
            return None
        return TaskRecord(
            task_id=model.id,
            task_type=TaskType(model.task_type),
            account_id=model.account_id,
            status=TaskStatus(model.status),
            started_at=model.started_at,
            completed_at=model.completed_at,
            error_message=model.error_message,
            retry_count=model.retry_count,
            max_retries=model.max_retries,
            result_data=model.result_data,
            execution_time_ms=model.execution_time_ms,
            ip_address=model.ip_address,
            user_agent=model.user_agent,
        )

    def get_failed_tasks_since(
        self,
        since: datetime,
    ) -> List[TaskRecord]:
        """Get all failed tasks since a timestamp for audit/retry."""
        models = (
            self.db.query(TaskModel)
            .filter(TaskModel.status == "failed")
            .filter(TaskModel.completed_at >= since)
            .order_by(TaskModel.completed_at.desc())
            .all()
        )
        return [
            TaskRecord(
                task_id=m.id,
                task_type=TaskType(m.task_type),
                account_id=m.account_id,
                status=TaskStatus.FAILED,
                started_at=m.started_at,
                completed_at=m.completed_at,
                error_message=m.error_message,
                retry_count=m.retry_count,
                max_retries=m.max_retries,
                result_data=m.result_data,
                execution_time_ms=m.execution_time_ms,
                ip_address=m.ip_address,
                user_agent=m.user_agent,
            )
            for m in models
        ]

    def get_task_stats(self) -> Dict[str, Any]:
        """Get task execution statistics."""
        total = self.db.query(TaskModel).count()
        by_status: Dict[str, int] = {}
        for status in TaskStatus:
            count = self.db.query(TaskModel).filter(TaskModel.status == status.value).count()
            by_status[status.value] = count
        avg_time = (
            self.db.query(
                TaskModel.execution_time_ms
            )
            .filter(TaskModel.execution_time_ms.isnot(None))
            .all()
        )
        avg_ms = sum(t[0] for t in avg_time if t[0]) / len(avg_time) if avg_time else 0
        return {
            "total_tasks": total,
            "status_breakdown": by_status,
            "average_execution_time_ms": round(avg_ms, 2),
        }


# Convenience function to create task logger
def make_task_logger(db: Session) -> TaskLogger:
    return TaskLogger(db)


# Convenience function to create task manager
def make_task_manager() -> TaskLogger:
    return TaskLogger()