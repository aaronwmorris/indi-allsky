There is a typo in one of the INDI headers which causes the build for pyindi-client to fail. The INDI devs have fixed the problem in their repo, but I do not think the fix will be distributed until 2.0.5

https://github.com/indilib/indi/pull/1948

You will need to edit `/usr/include/libindi/indibase.h` (or `/usr/local/include/libindi/indibase.h`) and remove the space between % and "include" on line 10.

```diff
10c10
< % include "indiapi.h"
---
> %include "indiapi.h"
```