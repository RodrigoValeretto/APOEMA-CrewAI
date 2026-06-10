"""
Database manager wrapper for APOEMA
Provides a reusable interface for database operations shared between API and Dramatiq
"""
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from api.database import (
    create_analysis as db_create_analysis,
    get_analysis as db_get_analysis,
    get_all_analyses as db_get_all_analyses,
    update_analysis_status as db_update_analysis_status,
    save_analysis_result as db_save_analysis_result,
    get_analysis_results as db_get_analysis_results,
    delete_analysis as db_delete_analysis,
    create_analysis_file as db_create_analysis_file,
    get_analysis_file as db_get_analysis_file,
    delete_analysis_file as db_delete_analysis_file,
    count_completed_results as db_count_completed_results,
)
from api.exceptions import AnalysisNotFound, DatabaseError
from api.constants import AnalysisStatus


class DatabaseManager:
    """Wrapper for database operations"""

    def create_analysis(
        self,
        analysis_type: str,
        status: str = AnalysisStatus.PENDING.value,
    ) -> int:
        """
        Create a new analysis

        Args:
            analysis_type: Type of analysis (pdf, png_csv, basic)
            status: Initial status

        Returns:
            analysis_id
        """
        return db_create_analysis(analysis_type, status)

    def get_analysis(self, analysis_id: int) -> Dict[str, Any]:
        """Get analysis by ID"""
        return db_get_analysis(analysis_id)

    def get_all_analyses(
        self,
        skip: int = 0,
        limit: int = 10,
        analysis_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """Get paginated list of analyses"""
        return db_get_all_analyses(skip, limit, analysis_type, status)

    def update_status(self, analysis_id: int, status: str) -> None:
        """Update analysis status"""
        db_update_analysis_status(analysis_id, status)

    def save_result(
        self,
        analysis_id: int,
        task_name: str,
        result: str,
    ) -> int:
        """Save a task result"""
        return db_save_analysis_result(analysis_id, task_name, result)

    def get_results(
        self,
        analysis_id: int,
        task_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get all results for an analysis"""
        return db_get_analysis_results(analysis_id, task_name)

    def delete_analysis(self, analysis_id: int) -> None:
        """Delete an analysis"""
        db_delete_analysis(analysis_id)

    def create_file_record(
        self,
        analysis_id: Optional[int],
        file_type: str,
        file_name: str,
        file_path: str,
        file_size: int,
    ) -> int:
        """Create a file tracking record"""
        return db_create_analysis_file(
            analysis_id,
            file_type,
            file_name,
            file_path,
            file_size,
        )

    def get_file_record(self, file_id: int) -> Optional[Dict[str, Any]]:
        """Get file tracking record"""
        return db_get_analysis_file(file_id)

    def delete_file_record(self, file_id: int) -> None:
        """Delete file tracking record"""
        db_delete_analysis_file(file_id)

    def count_results(self, analysis_id: int) -> int:
        """Count number of results for an analysis"""
        return db_count_completed_results(analysis_id)


# Global instance
_db_manager: Optional[DatabaseManager] = None


def get_db_manager() -> DatabaseManager:
    """
    Get or create database manager instance (singleton pattern)

    Returns:
        DatabaseManager instance
    """
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


# Convenience functions for direct usage
def create_analysis(
    analysis_type: str,
    status: str = AnalysisStatus.PENDING.value,
) -> int:
    """Create a new analysis"""
    return get_db_manager().create_analysis(analysis_type, status)


def get_analysis(analysis_id: int) -> Dict[str, Any]:
    """Get analysis by ID"""
    return get_db_manager().get_analysis(analysis_id)


def update_analysis_status(analysis_id: int, status: str) -> None:
    """Update analysis status"""
    get_db_manager().update_status(analysis_id, status)


def save_analysis_result(analysis_id: int, task_name: str, result: str) -> int:
    """Save a task result"""
    return get_db_manager().save_result(analysis_id, task_name, result)


def get_analysis_results(
    analysis_id: int,
    task_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Get all results for an analysis"""
    return get_db_manager().get_results(analysis_id, task_name)


def delete_analysis(analysis_id: int) -> None:
    """Delete an analysis"""
    get_db_manager().delete_analysis(analysis_id)
