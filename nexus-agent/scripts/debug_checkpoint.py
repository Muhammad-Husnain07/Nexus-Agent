"""Debug checkpoint structure — inspect LangGraph checkpoint + StateSnapshot."""
import asyncio
import sys

async def main():
    SID = sys.argv[1] if len(sys.argv) > 1 else "479a5f72-c807-4908-bd48-e919fbafe5e8"
    
    from nexus.agent.runner import AgentRunner
    runner = AgentRunner()
    graph = await runner._build_graph()
    config = {"configurable": {"thread_id": SID}}
    
    # Get the latest state (StateSnapshot)
    latest = await graph.aget_state(config)
    if latest is None:
        print("No state found")
        return
    
    print("StateSnapshot attributes:")
    attrs = [a for a in dir(latest) if not a.startswith("_") and not callable(getattr(latest, a, None))]
    print(f"  {sorted(attrs)}")
    
    # Show key attributes
    for attr in ['next', 'values', 'config', 'parent_config', 'checkpoint', 'metadata', 'created_at', 'parent_checkpoint']:
        try:
            val = getattr(latest, attr, 'NOT_FOUND')
            if val != 'NOT_FOUND':
                val_str = str(val)
                print(f"  {attr}: {val_str[:200]}")
        except Exception as e:
            print(f"  {attr}: ERROR - {e}")
    
    # Check if config has checkpoint_id
    if hasattr(latest, 'config'):
        cfg = latest.config
        if isinstance(cfg, dict):
            cconf = cfg.get('configurable', {})
            print(f"  configurable keys: {list(cconf.keys())}")
            if 'checkpoint_id' in cconf:
                print(f"  checkpoint_id: {cconf['checkpoint_id']}")

asyncio.run(main())
