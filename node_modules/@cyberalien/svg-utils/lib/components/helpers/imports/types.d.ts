/**
 * List of imports for component
 */
interface FactoryComponentImports {
  default: Record<string, string>;
  named: Record<string, Set<string>>;
  types: Record<string, Set<string>>;
  full: Set<string>;
  css: Set<string>;
}
export { FactoryComponentImports };