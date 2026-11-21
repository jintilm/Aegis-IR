; Two natural loops with depth two and loop-carried SSA values. The lint pass
; must report these structural costs while leaving the complete module intact.
define i32 @nested_loops(i32 %n, i32 %m) #0 {
entry:
  br label %outer

outer:
  %i = phi i32 [ 0, %entry ], [ %next.i, %outer.latch ]
  %sum.outer = phi i32 [ 0, %entry ], [ %sum.inner, %outer.latch ]
  %more.i = icmp ult i32 %i, %n
  br i1 %more.i, label %inner, label %exit

inner:
  %j = phi i32 [ 0, %outer ], [ %next.j, %inner.body ]
  %sum.inner = phi i32 [ %sum.outer, %outer ], [ %sum.next, %inner.body ]
  %more.j = icmp ult i32 %j, %m
  br i1 %more.j, label %inner.body, label %outer.latch

inner.body:
  %product = mul i32 %i, %j
  %sum.next = add i32 %sum.inner, %product
  %next.j = add i32 %j, 1
  br label %inner

outer.latch:
  %next.i = add i32 %i, 1
  br label %outer

exit:
  ret i32 %sum.outer
}

attributes #0 = { "aegis.level"="3" }
