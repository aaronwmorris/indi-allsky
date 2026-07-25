/**
 * Find used animation names in content
 *
 * This function is opinionated, it is designed to find animation names in typical CSS content, but it may not cover all edge cases.
 * Assumes animation name uses only the following characters: a-z, 0-9, -, _ and starts with a letter.
 *
 * Might return false positives
 */
declare function findUsedKeyframes(content: string): string[];
export { findUsedKeyframes };