"""Fixed typed GUI actions. No source code is accepted from callers."""
import math
import re
from uuid import UUID
from tflex_bridge_read import decode, _error
from tflex_model_operations import ModelOperations
VERSION="geometry-stage1-2"
ACTIONS=("create_block","create_cylinder","boolean_unite","boolean_subtract","boolean_intersect")
TOOLS=ACTIONS+("get_geometry_operation_result",)

def uuid_ok(value):
    try: return type(value) is str and str(UUID(value))==value
    except (ValueError,TypeError,AttributeError): return False

def object_ref(value):
    if type(value) is not str or not 1<=len(value)<=132 or any(ord(c)<32 or ord(c)==127 for c in value):
        raise ValueError("Invalid operation reference")
    if value.startswith("oid:") and value[4:]: return value
    if re.fullmatch(r"[0-9]{1,10}",value) and 0<int(value)<=0xffffffff: return str(int(value))
    raise ValueError("Use returned oid: identifier or legacy numeric ID")

def number(value):
    if type(value) not in (int,float) or not math.isfinite(value): raise ValueError("Finite number required")
    return format(value,".17g")

def validate(action,args):
    if action not in ACTIONS or type(args) is not dict or any(type(v) is not str for v in args.values()): raise ValueError("Invalid geometry arguments")
    name=args.get("name","")
    if not name.strip() or len(name)>64 or any(ord(c)<32 or ord(c)==127 for c in name): raise ValueError("Name must contain 1..64 printable characters")
    expected={"name"}
    if action.startswith("create_"):
        dimensions=("size_x_mm","size_y_mm","size_z_mm") if action=="create_block" else ("diameter_mm","height_mm")
        for key in ("x_mm","y_mm","z_mm")+dimensions:
            expected.add(key); value=float(args[key])
            if not math.isfinite(value) or abs(value)>1e6 or (key in dimensions and value<0.001): raise ValueError("Invalid mm: "+key)
        if action=="create_cylinder":
            expected.add("axis")
            if args["axis"] not in ("X","Y","Z"): raise ValueError("Invalid axis")
    else:
        expected.update(("first_id","second_id"))
        first,second=object_ref(args["first_id"]),object_ref(args["second_id"])
        if first==second: raise ValueError("Operands must differ")
    if set(args)!=expected: raise ValueError("Missing or extra fields")
    return dict(args)

class GeometryOperations(ModelOperations):
    def _arguments(self,action,doc_id,args,resolve_paths):
        if action not in ACTIONS: return super()._arguments(action,doc_id,args,resolve_paths)
        if not uuid_ok(doc_id): raise ValueError("Document identity required")
        return {"action":action,"doc_id":doc_id,**{"arg."+k:v for k,v in validate(action,args).items()}}

    def submit(self,session_id,doc_id,job_id,action,arguments):
        try:
            if not all(uuid_ok(x) for x in (session_id,doc_id,job_id)): raise ValueError("Canonical session/document/job UUID required")
            validate(action,arguments)
            directory,identity=self._identity(session_id)
            if directory is None: return _error("session_unavailable")
            if decode(directory/"ready.txt").get("geometry_api")!=VERSION: return _error("geometry_plugin_not_installed_or_not_restarted")
            return super().submit(session_id,doc_id,job_id,action,arguments)
        except (ValueError,KeyError,TypeError,OverflowError) as exc: return _error("invalid_geometry_arguments",detail=str(exc))
        except OSError: return _error("geometry_handshake_unavailable")

    def status(self,session_id,job_id):
        if not uuid_ok(session_id) or not uuid_ok(job_id): return _error("invalid_session_or_job_id")
        result=super().status(session_id,job_id)
        if result.get("status")!="completed": return result
        if result.get("action") not in ACTIONS: return _error("not_geometry_job",job_id=job_id)
        try:
            directory,identity=self._identity(session_id)
            if directory is None: return _error("session_unavailable_outcome_unknown",job_id=job_id)
            raw=self.bridge._result(directory,identity,job_id)
            if raw.get("model_edit_completed")!="true" or raw.get("solid_result_checked")!="true" or raw.get("geometry_api")!=VERSION: return _error("geometry_execution_not_confirmed",job_id=job_id)
            created=object_ref(raw["created_operation_id"])
            count=int(raw["result_solid_count"])
            spans=[float(v) for v in raw["bbox_span_mm"].split(",")]
            if count<1 or len(spans)!=3 or any(not math.isfinite(v) or v<=0 for v in spans): raise ValueError("Invalid result dimensions")
            result.update(rebuilt=True,created_operation_id=created,result_solid_count=count,bbox_span_mm=spans,bbox_dimensions_checked=raw.get("bbox_dimensions_checked")=="true",geometry_verified=False)
            return result
        except (OSError,ValueError,KeyError,TypeError): return _error("geometry_result_unavailable_do_not_repeat",job_id=job_id)

def register_geometry_tools(server,bridge,workspace,enabled):
    operations=GeometryOperations(bridge,workspace)
    def submit(action,session_id,doc_id,job_id,args):
        if not enabled: return _error("bridge_edits_disabled")
        return operations.submit(session_id,doc_id,job_id,action,args)
    def inputs(name,fields): return {"name":name,**{k:number(v) for k,v in fields}}
    @server.tool()
    def create_block(session_id:str,doc_id:str,job_id:str,name:str,size_x_mm:float,size_y_mm:float,size_z_mm:float,x_mm:float=0,y_mm:float=0,z_mm:float=0)->dict:
        """Create a centered block in the selected GUI document. All sizes and center coordinates in mm. One exact action, no save. Read get_geometry_operation_result with the same UUID job_id."""
        try: args=inputs(name,(("size_x_mm",size_x_mm),("size_y_mm",size_y_mm),("size_z_mm",size_z_mm),("x_mm",x_mm),("y_mm",y_mm),("z_mm",z_mm)))
        except (ValueError,TypeError,OverflowError) as exc: return _error("invalid_geometry_arguments",detail=str(exc))
        return submit("create_block",session_id,doc_id,job_id,args)
    @server.tool()
    def create_cylinder(session_id:str,doc_id:str,job_id:str,name:str,diameter_mm:float,height_mm:float,x_mm:float=0,y_mm:float=0,z_mm:float=0,axis:str="Z")->dict:
        """Create a centered cylinder along X/Y/Z in the selected GUI document. Diameter, full height, center in mm. No save."""
        try: args={**inputs(name,(("diameter_mm",diameter_mm),("height_mm",height_mm),("x_mm",x_mm),("y_mm",y_mm),("z_mm",z_mm))),"axis":axis}
        except (ValueError,TypeError,OverflowError) as exc: return _error("invalid_geometry_arguments",detail=str(exc))
        return submit("create_cylinder",session_id,doc_id,job_id,args)
    @server.tool()
    def boolean_unite(session_id:str,doc_id:str,job_id:str,name:str,first_id:str,second_id:str)->dict:
        """Unite two distinct top-level solid operations in the selected document. Pass opaque oid: IDs returned by the tools, or legacy numeric IDs. No save."""
        return submit("boolean_unite",session_id,doc_id,job_id,{"name":name,"first_id":first_id,"second_id":second_id})
    @server.tool()
    def boolean_subtract(session_id:str,doc_id:str,job_id:str,name:str,first_id:str,second_id:str)->dict:
        """Subtract second_id from first_id in the selected GUI document. Nonempty solid result required. Preserve returned oid: IDs unchanged. No save."""
        return submit("boolean_subtract",session_id,doc_id,job_id,{"name":name,"first_id":first_id,"second_id":second_id})
    @server.tool()
    def boolean_intersect(session_id:str,doc_id:str,job_id:str,name:str,first_id:str,second_id:str)->dict:
        """Intersect two distinct solid operations in the selected document. Empty result is not reported as success. No save."""
        return submit("boolean_intersect",session_id,doc_id,job_id,{"name":name,"first_id":first_id,"second_id":second_id})
    @server.tool()
    def get_geometry_operation_result(session_id:str,job_id:str)->dict:
        """Read existing geometry job: created oid:, solid count, bbox checks. Never resubmit on timeout. Does not verify all geometry independently."""
        if not enabled: return _error("bridge_edits_disabled")
        return operations.status(session_id,job_id)
