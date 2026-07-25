declare const defaultClassProp = "class";
declare const classProps: readonly ["class"];
type ClassProp = (typeof classProps)[number];
export { ClassProp, classProps, defaultClassProp };