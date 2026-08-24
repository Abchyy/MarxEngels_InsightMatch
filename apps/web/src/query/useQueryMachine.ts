import { useEffect, useRef, useState } from "react";
import { QueryMachine, type QueryMachineDeps, type QueryState } from "./queryMachine";

/** 每次渲染都透传最新 deps，避免闭包捕获过期的 scope 构建器。 */
export function useQueryMachine(deps: QueryMachineDeps) {
  const depsRef = useRef(deps);
  useEffect(() => {
    depsRef.current = deps;
  });

  const [machine] = useState(
    () =>
      new QueryMachine({
        suggestMode: (query, signal) => depsRef.current.suggestMode(query, signal),
        search: (request, signal) => depsRef.current.search(request, signal),
        buildRequest: (query, mode) => depsRef.current.buildRequest(query, mode),
      }),
  );
  const [state, setState] = useState<QueryState>(() => machine.getState());

  useEffect(() => machine.subscribe(setState), [machine]);
  useEffect(() => () => machine.dispose(), [machine]);

  return { state, machine };
}
