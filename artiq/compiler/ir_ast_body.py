import ast
from copy import copy

from llvm import core as lc

from artiq.compiler import ir_values

class Visitor:
	def __init__(self, env, ns, builder=None):
		self.env = env
		self.ns = ns
		self.builder = builder

	# builder can be None for visit_expression
	def visit_expression(self, node):
		method = "_visit_expr_" + node.__class__.__name__
		try:
			visitor = getattr(self, method)
		except AttributeError:
			raise NotImplementedError("Unsupported node '{}' in expression".format(node.__class__.__name__))
		return visitor(node)

	def _visit_expr_Name(self, node):
		try:
			r = self.ns[node.id]
		except KeyError:
			raise NameError("Name '{}' is not defined".format(node.id))
		r = copy(r)
		if self.builder is None:
			r.llvm_value = None
		else:
			if isinstance(r.llvm_value, lc.AllocaInstruction):
				r.llvm_value = self.builder.load(r.llvm_value)
		return r

	def _visit_expr_NameConstant(self, node):
		v = node.value
		if v is None:
			r = ir_values.VNone()
		elif isinstance(v, bool):
			r = ir_values.VBool()
		else:
			raise NotImplementedError
		if self.builder is not None:
			r.create_constant(v)
		return r

	def _visit_expr_Num(self, node):
		n = node.n
		if isinstance(n, int):
			if abs(n) < 2**31:
				r = ir_values.VInt()
			else:
				r = ir_values.VInt(64)
		else:
			raise NotImplementedError
		if self.builder is not None:
			r.create_constant(n)
		return r

	def _visit_expr_UnaryOp(self, node):
		ast_unops = {
			ast.Invert: ir_values.operators.inv,
			ast.Not: ir_values.operators.not_,
			ast.UAdd: ir_values.operators.pos,
			ast.USub: ir_values.operators.neg
		}
		return ast_unops[type(node.op)](self.visit_expression(node.operand), self.builder)

	def _visit_expr_BinOp(self, node):
		ast_binops = {
			ast.Add: ir_values.operators.add,
			ast.Sub: ir_values.operators.sub,
			ast.Mult: ir_values.operators.mul,
			ast.Div: ir_values.operators.truediv,
			ast.FloorDiv: ir_values.operators.floordiv,
			ast.Mod: ir_values.operators.mod,
			ast.Pow: ir_values.operators.pow,
			ast.LShift: ir_values.operators.lshift,
			ast.RShift: ir_values.operators.rshift,
			ast.BitOr: ir_values.operators.or_,
			ast.BitXor: ir_values.operators.xor,
			ast.BitAnd: ir_values.operators.and_
		}
		return ast_binops[type(node.op)](self.visit_expression(node.left), self.visit_expression(node.right), self.builder)

	def _visit_expr_Compare(self, node):
		ast_cmps = {
			ast.Eq: ir_values.operators.eq,
			ast.NotEq: ir_values.operators.ne,
			ast.Lt: ir_values.operators.lt,
			ast.LtE: ir_values.operators.le,
			ast.Gt: ir_values.operators.gt,
			ast.GtE: ir_values.operators.ge
		}
		comparisons = []
		old_comparator = self.visit_expression(node.left)
		for op, comparator_a in zip(node.ops, node.comparators):
			comparator = self.visit_expression(comparator_a)
			comparison = ast_cmps[type(op)](old_comparator, comparator)
			comparisons.append(comparison)
			old_comparator = comparator
		r = comparisons[0]
		for comparison in comparisons[1:]:
			r = ir_values.operators.and_(r, comparison)
		return r

	def _visit_expr_Call(self, node):
		ast_unfuns = {
			"bool": ir_values.operators.bool,
			"int": ir_values.operators.int,
			"int64": ir_values.operators.int64,
			"round": ir_values.operators.round,
			"round64": ir_values.operators.round64,
		}
		fn = node.func.id
		if fn in ast_unfuns:
			return ast_unfuns[fn](self.visit_expression(node.args[0]), self.builder)
		elif fn == "syscall":
			return self.env.syscall(node.args[0].s,
				[self.visit_expression(expr) for expr in node.args[1:]],
				self.builder)
		else:
			raise NameError("Function '{}' is not defined".format(fn))

	def visit_statements(self, stmts):
		for node in stmts:
			method = "_visit_stmt_" + node.__class__.__name__
			try:
				visitor = getattr(self, method)
			except AttributeError:
				raise NotImplementedError("Unsupported node '{}' in statement".format(node.__class__.__name__))
			visitor(node)

	def _visit_stmt_Assign(self, node):
		val = self.visit_expression(node.value)
		for target in node.targets:
			if isinstance(target, ast.Name):
				self.builder.store(val, self.ns[target.id])
			else:
				raise NotImplementedError

	def _visit_stmt_AugAssign(self, node):
		val = self.visit_expression(ast.BinOp(op=node.op, left=node.target, right=node.value))
		if isinstance(node.target, ast.Name):
			self.builder.store(val, self.ns[node.target.id])
		else:
			raise NotImplementedError

	def _visit_stmt_Expr(self, node):
		self.visit_expression(node.value)

	def _visit_stmt_If(self, node):
		function = self.builder.basic_block.function
		then_block = function.append_basic_block("i_then")
		else_block = function.append_basic_block("i_else")
		merge_block = function.append_basic_block("i_merge")

		condition = ir_values.operators.bool(self.visit_expression(node.test), self.builder)
		self.builder.cbranch(condition.llvm_value, then_block, else_block)

		self.builder.position_at_end(then_block)
		self.visit_statements(node.body)
		self.builder.branch(merge_block)

		self.builder.position_at_end(else_block)
		self.visit_statements(node.orelse)
		self.builder.branch(merge_block)

		self.builder.position_at_end(merge_block)

	def _visit_stmt_While(self, node):
		function = self.builder.basic_block.function
		body_block = function.append_basic_block("w_body")
		else_block = function.append_basic_block("w_else")
		merge_block = function.append_basic_block("w_merge")

		condition = self.visit_expression(node.test)
		self.builder.cbranch(condition, body_block, else_block)

		self.builder.position_at_end(body_block)
		self.visit_statements(node.body)
		condition = ir_values.operators.bool(self.visit_expression(node.test), self.builder)
		self.builder.cbranch(condition.llvm_value, body_block, merge_block)

		self.builder.position_at_end(else_block)
		self.visit_statements(node.orelse)
		self.builder.branch(merge_block)

		self.builder.position_at_end(merge_block)