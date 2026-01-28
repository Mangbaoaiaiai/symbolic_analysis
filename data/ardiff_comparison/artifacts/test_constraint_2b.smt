
; 等价测试约束2B
(set-info :status unknown)
(declare-fun y () (_ BitVec 32))
(assert (not (and (bvuge y (_ bv3 32)) (bvule y (_ bv7 32)))))
(check-sat)
