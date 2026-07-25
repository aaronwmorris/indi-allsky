/**
 * Method of importing CSS in generated components
 *
 * 'import' - Create external CSS file and import it in component
 * 'embed' - Embed CSS styles in component (if supported by component, throws error otherwise)
 * 'prop' - Export CSS as separate property in generated data, do not import in component, do not create asset
 */
type CSSExportMode = 'import' | 'embed' | 'prop';
export { CSSExportMode };