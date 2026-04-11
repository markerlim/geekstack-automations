"""Utility functions for scraper backup management"""

import os
import glob
from datetime import datetime, timedelta


def cleanup_old_backups(db_folder, backup_prefix, days=7):
    """
    Remove backup files older than specified days
    
    Args:
        db_folder: Folder where backups are stored (e.g., 'fullaheaddb')
        backup_prefix: Prefix of backup files (e.g., 'fullahead_cardlist_backup_')
        days: Number of days to keep (default 7)
    
    Returns:
        dict: Statistics about deleted and kept backups
    """
    try:
        os.makedirs(db_folder, exist_ok=True)
        
        # Get current time
        now = datetime.now()
        cutoff_time = now - timedelta(days=days)
        
        # Find all backup files matching pattern
        backup_pattern = f"{db_folder}/{backup_prefix}*.json"
        backup_files = glob.glob(backup_pattern)
        
        if not backup_files:
            print(f"ℹ️ No backup files found to cleanup in {db_folder}")
            return {'deleted': 0, 'kept': 0, 'deleted_files': []}
        
        deleted_count = 0
        kept_count = 0
        deleted_files = []
        
        for backup_file in backup_files:
            # Get file modification time
            file_mtime = datetime.fromtimestamp(os.path.getmtime(backup_file))
            
            if file_mtime < cutoff_time:
                # Delete old backup
                os.remove(backup_file)
                deleted_count += 1
                deleted_files.append(os.path.basename(backup_file))
                print(f"  🗑️ Deleted: {os.path.basename(backup_file)} (from {file_mtime.strftime('%Y-%m-%d %H:%M:%S')})")
            else:
                kept_count += 1
        
        print(f"✅ Cleanup complete: Deleted {deleted_count} old backups, keeping {kept_count} recent backups (last {days} days)")
        
        return {
            'deleted': deleted_count,
            'kept': kept_count,
            'deleted_files': deleted_files
        }
    
    except Exception as e:
        print(f"❌ Error during cleanup: {str(e)}")
        return {'deleted': 0, 'kept': 0, 'deleted_files': [], 'error': str(e)}
