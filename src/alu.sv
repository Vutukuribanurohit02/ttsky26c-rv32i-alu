// alu.sv - RV32I Arithmetic Logic Unit
// Implements the 10 ALU operations needed by RV32I R-type and I-type
// instructions. Purely combinational -- no clock, no state.

module alu #(
    parameter int WIDTH = 32
)(
    input  logic [WIDTH-1:0] a,
    input  logic [WIDTH-1:0] b,
    input  logic [3:0]       alu_op,
    output logic [WIDTH-1:0] result,
    output logic             zero
);

    // Operation encoding (matches typical RV32I ALU control conventions)
    localparam logic [3:0]
        ALU_ADD  = 4'b0000,
        ALU_SUB  = 4'b0001,
        ALU_AND  = 4'b0010,
        ALU_OR   = 4'b0011,
        ALU_XOR  = 4'b0100,
        ALU_SLT  = 4'b0101,  // set less than, signed
        ALU_SLTU = 4'b0110,  // set less than, unsigned
        ALU_SLL  = 4'b0111,  // shift left logical
        ALU_SRL  = 4'b1000,  // shift right logical (zero-fill)
        ALU_SRA  = 4'b1001;  // shift right arithmetic (sign-extend)

    // Shift amount: RV32I only uses the low 5 bits of the shift operand
    logic [4:0] shamt;
    assign shamt = b[4:0];

    always_comb begin
        case (alu_op)
            ALU_ADD:  result = a + b;
            ALU_SUB:  result = a - b;
            ALU_AND:  result = a & b;
            ALU_OR:   result = a | b;
            ALU_XOR:  result = a ^ b;
            ALU_SLT:  result = {{(WIDTH-1){1'b0}}, ($signed(a) < $signed(b))};
            ALU_SLTU: result = {{(WIDTH-1){1'b0}}, (a < b)};
            ALU_SLL:  result = a << shamt;
            ALU_SRL:  result = a >> shamt;
            ALU_SRA:  result = $signed(a) >>> shamt;
            default:  result = '0;
        endcase
    end

    assign zero = (result == '0);

endmodule
