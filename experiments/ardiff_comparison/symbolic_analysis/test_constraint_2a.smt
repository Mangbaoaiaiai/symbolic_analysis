
; 等价测试约束2A
(set-info :status unknown)
(declare-fun y () (_ BitVec 32))
(assert (or (bvult y (_ bv3 32)) (bvugt y (_ bv7 32))))
(check-sat)
