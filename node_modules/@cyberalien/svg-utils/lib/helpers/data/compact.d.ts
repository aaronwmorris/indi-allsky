interface ContextItemData<T> {
  parent: Record<string, unknown>;
  key: string;
  actualValue?: T;
}
interface ContextItem<T> {
  map: Map<string, ContextItemData<T> | number>;
  data: T[];
}
/**
 * Create context item for minification
 */
declare function createCompactContext<T>(): ContextItem<T>;
/**
 * Minify item
 *
 * If value is not a string, set it in `actualValue` and string `value` for comparison
 */
declare function compactItem<T>(context: ContextItem<T>, stringifiedValue: string, parent: Record<string, unknown>, key: string, actualValue?: T): void;
export { compactItem, createCompactContext };