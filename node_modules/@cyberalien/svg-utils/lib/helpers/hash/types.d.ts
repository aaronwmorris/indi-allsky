/**
 * Context for hashing functions, used to ensure uniqueness
 */
interface HashContext {
  cache?: Record<string, string>;
}
/**
 * Length option for hash
 */
type LengthOption = number | ((content: string) => number);
/**
 * Partial options, used for extending type
 */
interface UniqueHashPartialOptions {
  context: HashContext;
  prefix?: string;
  length?: LengthOption;
  lengths?: Record<string, number>;
  throwOnCollision?: boolean;
}
/**
 * Options for unique hash generation
 */
interface UniqueHashOptions extends UniqueHashPartialOptions {
  css: boolean;
  length: LengthOption;
}
export { HashContext, UniqueHashOptions, UniqueHashPartialOptions };