/**
 * Dynamic property value
 */
interface FactoryComponentDynamicProp {
  type?: string;
  required?: boolean;
  value?: string;
  template?: string;
}
/**
 * Properties for component
 */
type FactoryComponentProps = Record<string, string | FactoryComponentDynamicProp>;
export { FactoryComponentDynamicProp, FactoryComponentProps };