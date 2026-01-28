
; 等价测试约束1B
(set-info :status unknown)
(declare-fun x () (_ BitVec 32))
(assert (and (bvuge x (_ bv5 32)) (bvule x (_ bv10 32))))
(check-sat)
