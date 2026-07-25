/**
 * Fallback replacement for boolean state
 */
interface IconFallbackBooleanState {
  state: string;
  values: [string, string];
}
/**
 * Fallback for named state
 *
 * Value should match state values
 */
interface IconFallbackAdvancedState {
  state: string;
}
/**
 * Template for fallback: mix of strings and states
 */
type IconFallbackTemplate = (string | IconFallbackBooleanState | IconFallbackAdvancedState)[];
export { IconFallbackAdvancedState, IconFallbackBooleanState, IconFallbackTemplate };