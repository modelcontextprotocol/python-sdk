"""
Utility functions for handling tool versioning and semantic version constraints.

This module provides functionality to parse and validate semantic version constraints
as specified in SEP-1575: Tool Semantic Versioning.
"""

import re
from typing import Any, Dict, List, Optional, Tuple


class VersionConstraintError(Exception):
    """Raised when a version constraint cannot be satisfied."""
    pass


class InvalidVersionError(Exception):
    """Raised when a version string is invalid."""
    pass


def parse_version(version_str: str) -> Tuple[int, int, int, Optional[str]]:
    """
    Parse a semantic version string into its components.
    
    Args:
        version_str: Version string in SemVer format (e.g., "1.2.3", "2.0.0-alpha.1")
        
    Returns:
        Tuple of (major, minor, patch, prerelease)
        
    Raises:
        InvalidVersionError: If the version string is invalid
    """
    # SemVer regex pattern
    pattern = r'^(\d+)\.(\d+)\.(\d+)(?:-([a-zA-Z0-9.-]+))?(?:\+([a-zA-Z0-9.-]+))?$'
    match = re.match(pattern, version_str)
    
    if not match:
        raise InvalidVersionError(f"Invalid version string: {version_str}")
    
    major, minor, patch, prerelease, build = match.groups()
    return int(major), int(minor), int(patch), prerelease


def compare_versions(version1: str, version2: str) -> int:
    """
    Compare two semantic versions.
    
    Args:
        version1: First version string
        version2: Second version string
        
    Returns:
        -1 if version1 < version2, 0 if equal, 1 if version1 > version2
    """
    try:
        major1, minor1, patch1, prerelease1 = parse_version(version1)
        major2, minor2, patch2, prerelease2 = parse_version(version2)
    except InvalidVersionError:
        raise InvalidVersionError(f"Invalid version strings: {version1}, {version2}")
    
    # Compare major, minor, patch
    if major1 != major2:
        return -1 if major1 < major2 else 1
    if minor1 != minor2:
        return -1 if minor1 < minor2 else 1
    if patch1 != patch2:
        return -1 if patch1 < patch2 else 1
    
    # Compare prerelease versions
    if prerelease1 is None and prerelease2 is None:
        return 0
    if prerelease1 is None:
        return 1  # Stable version is greater than prerelease
    if prerelease2 is None:
        return -1  # Prerelease is less than stable version
    
    # Compare prerelease strings lexicographically
    if prerelease1 < prerelease2:
        return -1
    elif prerelease1 > prerelease2:
        return 1
    else:
        return 0


def satisfies_constraint(version: str, constraint: str) -> bool:
    """
    Check if a version satisfies a given constraint.
    
    Args:
        version: Version string to check
        constraint: Version constraint (e.g., "^1.2.3", "~1.4.1", ">=2.0.0", "1.2.3")
        
    Returns:
        True if the version satisfies the constraint, False otherwise
    """
    try:
        major, minor, patch, prerelease = parse_version(version)
    except InvalidVersionError:
        return False
    
    # Handle exact version
    if not any(op in constraint for op in ['^', '~', '>', '<', '=', '!']):
        return compare_versions(version, constraint) == 0
    
    # Handle caret (^) - allows non-breaking updates
    if constraint.startswith('^'):
        target_version = constraint[1:]
        try:
            target_major, target_minor, target_patch, target_prerelease = parse_version(target_version)
        except InvalidVersionError:
            return False
        
        # ^1.2.3 is equivalent to >=1.2.3 <2.0.0
        if major != target_major:
            return False
        if major == target_major:
            if minor < target_minor:
                return False
            if minor == target_minor and patch < target_patch:
                return False
        return True
    
    # Handle tilde (~) - allows patch-level updates
    if constraint.startswith('~'):
        target_version = constraint[1:]
        try:
            target_major, target_minor, target_patch, target_prerelease = parse_version(target_version)
        except InvalidVersionError:
            return False
        
        # ~1.2.3 is equivalent to >=1.2.3 <1.3.0
        if major != target_major or minor != target_minor:
            return False
        return patch >= target_patch
    
    # Handle comparison operators
    if constraint.startswith('>='):
        target_version = constraint[2:]
        return compare_versions(version, target_version) >= 0
    elif constraint.startswith('<='):
        target_version = constraint[2:]
        return compare_versions(version, target_version) <= 0
    elif constraint.startswith('>'):
        target_version = constraint[1:]
        return compare_versions(version, target_version) > 0
    elif constraint.startswith('<'):
        target_version = constraint[1:]
        return compare_versions(version, target_version) < 0
    elif constraint.startswith('='):
        target_version = constraint[1:]
        return compare_versions(version, target_version) == 0
    
    return False


def find_best_version(available_versions: List[str], constraint: str) -> Optional[str]:
    """
    Find the best version that satisfies a constraint from a list of available versions.
    
    Args:
        available_versions: List of available version strings
        constraint: Version constraint
        
    Returns:
        The best version that satisfies the constraint, or None if none satisfy it
    """
    satisfying_versions = [v for v in available_versions if satisfies_constraint(v, constraint)]
    
    if not satisfying_versions:
        return None
    
    # Sort versions and return the latest stable version
    # Prefer stable versions over prerelease versions
    stable_versions = [v for v in satisfying_versions if not parse_version(v)[3]]
    prerelease_versions = [v for v in satisfying_versions if parse_version(v)[3]]
    
    if stable_versions:
        # Return the latest stable version
        return max(stable_versions, key=lambda v: parse_version(v)[:3])
    else:
        # Return the latest prerelease version if no stable versions satisfy
        return max(prerelease_versions, key=lambda v: parse_version(v)[:3])


def validate_tool_requirements(
    tool_requirements: Dict[str, str], 
    available_tools: Dict[str, List[str]]
) -> Dict[str, str]:
    """
    Validate tool requirements against available tool versions.
    
    Args:
        tool_requirements: Dictionary mapping tool names to version constraints
        available_tools: Dictionary mapping tool names to lists of available versions
        
    Returns:
        Dictionary mapping tool names to selected versions
        
    Raises:
        VersionConstraintError: If any tool requirement cannot be satisfied
    """
    selected_versions = {}
    
    for tool_name, constraint in tool_requirements.items():
        if tool_name not in available_tools:
            raise VersionConstraintError(f"Tool '{tool_name}' not found")
        
        available_versions = available_tools[tool_name]
        if not available_versions:
            raise VersionConstraintError(f"No versions available for tool '{tool_name}'")
        
        best_version = find_best_version(available_versions, constraint)
        if best_version is None:
            raise VersionConstraintError(
                f"Tool requirement for '{tool_name}' ({constraint}) could not be satisfied. "
                f"Available versions: {available_versions}"
            )
        
        selected_versions[tool_name] = best_version
    
    return selected_versions